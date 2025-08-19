#--------------------------------#
# Makefile for Event-Driven POC  #
#--------------------------------#

SHELL := /bin/bash
.ONESHELL:
.DEFAULT_GOAL := help

#===================#
# Config Variables  #
#===================#
AWS_ACCT ?= 228122752878
AWS_DEFAULT_REGION ?= us-east-1

CLUSTER_NAME ?= event-driven-poc
APP_NS ?= event-poc
ELB_NS ?= aws-elb-controller-namespace

WINDOWS_AMI ?= ami-02b60b5095d1e5227
WINDOWS_SCRIPT_URL ?= https://raw.githubusercontent.com/robreris/event-poc-app/refs/heads/main/eks/v2/windows-ppt/windows-userdata.ps1
KEY_NAME ?= fgt-kp

# Versioned folder: v1 or v2 (etc.)
VERS ?= v1

#===================#
# Helpers           #
#===================#
define require_vers
if [ -z "$(VERS)" ]; then
  echo "VERS is required (e.g., make up VERS=v1)"; exit 1
fi
endef

define cluster_info
CLUSTER_INFO=$$(eksctl get cluster --name "$(CLUSTER_NAME)" --region "$(AWS_DEFAULT_REGION)" -o json)
VPC_ID=$$(echo "$$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.VpcId')
SUBNET_IDS=$$(echo "$$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.SubnetIds[]' | head -n 2)
SUBNET_ID_1=$$(echo "$$SUBNET_IDS" | sed -n '1p')
SUBNET_ID_2=$$(echo "$$SUBNET_IDS" | sed -n '2p')
SG_ID=$$(aws ec2 describe-instances --filters "Name=tag:eks:cluster-name,Values=$(CLUSTER_NAME)" --query 'Reservations[*].Instances[*].SecurityGroups[*].GroupId' --output text | uniq)
echo "#### Cluster VPC Info ####"
echo "VPC Id: $$VPC_ID"
echo "Subnet ID 1: $$SUBNET_ID_1"
echo "Subnet ID 2: $$SUBNET_ID_2"
echo "Cluster Security Group: $$SG_ID"
endef

define get_role_output
aws cloudformation describe-stacks --stack-name eks-addon-roles \
  --query "Stacks[0].Outputs[?OutputKey=='$(1)'].OutputValue" --output text
endef

define get_oidc_id
OIDC_ID=$$(aws eks describe-cluster --name $(CLUSTER_NAME) --query "cluster.identity.oidc.issuer" --output text | cut -d'/' -f5)
if [ -z "$$OIDC_ID" ]; then
  echo "OIDC Id not found."; exit 1
fi
echo $$OIDC_ID
endef

#===================#
# Top-level targets #
#===================#

.PHONY: help
help:
	@echo ""
	@echo "Event-Driven POC Makefile"
	@echo ""
	@echo "Primary:"
	@echo "  make up VERS=v1           # Full setup (cluster -> roles -> EFS -> ESO -> RabbitMQ)"
	@echo "  make down VERS=v1         # Tear everything down (manifests, stacks, cluster)"
	@echo ""
	@echo "Common steps:"
	@echo "  make cluster VERS=v1      # Create cluster + namespaces"
	@echo "  make roles VERS=v1        # OIDC + IAM role stack"
	@echo "  make extract-roles        # Poll and show role ARNs"
	@echo "  make sa VERS=v1           # Patch and create service accounts"
	@echo "  make efs VERS=v1          # EFS addon + FS + SC + PVC"
	@echo "  make eso                  # External Secrets Operator"
	@echo "  make alb                  # AWS Load Balancer Controller (optional)"
	@echo "  make rabbit VERS=v1       # RabbitMQ operator + cluster + app secret copy"
	@echo "  make rabbit-info VERS=v1  # Print RabbitMQ endpoints and creds"
	@echo "  make windows VERS=v2      # Create Windows EC2 component (v2 flow)"
	@echo "  make creds APP_NS=foo     # Copy Rabbit creds into another namespace"
	@echo ""

.PHONY: up
up: check cluster roles extract-roles sa efs efs-id eso rabbit rabbit-info
	@echo "✅ All done."

.PHONY: check
check:
	@$(require_vers)
	@echo "Launching $(VERS) setup…"

#===================#
# Cluster           #
#===================#
.PHONY: cluster
cluster:
	set -euo pipefail
	eksctl create cluster -f eks/$(VERS)/event-poc-cluster.yaml
	kubectl create namespace $(APP_NS) || true
	kubectl create namespace $(ELB_NS) || true
	@$(cluster_info)

.PHONY: info
info:
	@$(cluster_info)

#===================#
# IAM/OIDC + Roles  #
#===================#
.PHONY: roles
roles:
	set -euo pipefail
	eksctl utils associate-iam-oidc-provider --cluster "$(CLUSTER_NAME)" --approve
	OIDC_ID=$$($(get_oidc_id))
	echo "OIDC ID: $$OIDC_ID"
	aws cloudformation create-stack --stack-name eks-addon-roles \
	  --template-body file://./iam/$(VERS)/sa-roles-cft.yml \
	  --parameters \
	    ParameterKey=ClusterName,ParameterValue=$(CLUSTER_NAME) \
	    ParameterKey=OIDCId,ParameterValue=$$OIDC_ID \
	    ParameterKey=Namespace,ParameterValue=$(APP_NS) \
	  --capabilities CAPABILITY_NAMED_IAM \
	  --region $(AWS_DEFAULT_REGION)
	echo "⏳  Waiting for SA roles..."
	aws cloudformation wait stack-create-complete --stack-name eks-addon-roles

.PHONY: extract-roles
extract-roles:
	set -euo pipefail
	for role_key in EFSCSIRoleArn ESORoleArn ALBIngressRoleArn FrontendS3RoleArn; do \
	  for i in $$(seq 1 30); do \
	    role_value=$$($(call get_role_output,$$role_key)); \
	    if [ -n "$$role_value" ]; then \
	      printf "%s=%s\n" "$$role_key" "$$role_value"; \
	      break; \
	    fi; \
	    echo "🔄 Waiting for $$role_key… ($$i/30)"; \
	    sleep 10; \
	  done; \
	done

#===================#
# Service Accounts  #
#===================#
.PHONY: sa
sa:
	set -euo pipefail
	EFSCSIRoleArn=$$($(call get_role_output,EFSCSIRoleArn))
	ESORoleArn=$$($(call get_role_output,ESORoleArn))
	ALBIngressRoleArn=$$($(call get_role_output,ALBIngressRoleArn))
	FrontendS3RoleArn=$$($(call get_role_output,FrontendS3RoleArn))
	sed -i "s/^\(\s*namespace:\s*\).*/\1$(APP_NS)/" eks/$(VERS)/service-accounts/sa.yml
	sed -i "/name: efs-csi-controller-sa/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $$EFSCSIRoleArn#" eks/$(VERS)/service-accounts/sa.yml
	sed -i "/name: eso-sa/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $$ESORoleArn#" eks/$(VERS)/service-accounts/sa.yml
	sed -i "/name: frontend-s3-sa/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $$FrontendS3RoleArn#" eks/$(VERS)/service-accounts/sa.yml
	sed -i "/name: aws-alb-ingress-controller/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $$ALBIngressRoleArn#" eks/$(VERS)/service-accounts/sa.yml
	sed -i "/name: aws-alb-ingress-controller/,/namespace:/ s#^\([[:space:]]*namespace:\).*#\1 $(ELB_NS)#" eks/$(VERS)/service-accounts/sa.yml
	kubectl create -f eks/$(VERS)/service-accounts/sa.yml

#===================#
# EFS + PVC         #
#===================#
.PHONY: efs
efs:
	set -euo pipefail
	EFSCSIRoleArn=$$($(call get_role_output,EFSCSIRoleArn))
	echo "📦 Installing EFS CSI driver add-on with role: $$EFSCSIRoleArn"
	eksctl create addon \
	  --cluster "$(CLUSTER_NAME)" \
	  --name aws-efs-csi-driver \
	  --version latest \
	  --service-account-role-arn $$EFSCSIRoleArn \
	  --force
	echo "💾 Creating EFS filesystem…"
	sed -i "s/CLUSTER_NAME=.*/CLUSTER_NAME=\"$(CLUSTER_NAME)\"/" eks/$(VERS)/efs/create-efs.sh
	./eks/$(VERS)/efs/create-efs.sh $(VERS)
	echo "Creating Shared Artifacts PVC for apps…"
	sed -i "s/namespace=.*/namespace=\"$(CLUSTER_NAME)\"/" eks/$(VERS)/storage/shared-artifacts-pvc.yaml
	kubectl create -f eks/$(VERS)/storage/shared-artifacts-pvc.yaml
	echo "⏳  Waiting for EFS id…"
	for i in $$(seq 1 30); do \
	  EFS_ID=$$(aws efs describe-file-systems --query "FileSystems[?Tags[?Key=='Name' && Value=='$(CLUSTER_NAME)-efs']].FileSystemId" --output text); \
	  if [ -n "$$EFS_ID" ]; then break; fi; \
	  echo "🔄 Waiting… ($$i/30)"; sleep 10; \
	done
	echo "📄 Patching StorageClass with EFS ID: $$EFS_ID"
	sed -i "s/fileSystemId: .*/fileSystemId: $$EFS_ID/" eks/$(VERS)/efs/efs-sc.yaml
	kubectl create -f eks/$(VERS)/efs/efs-sc.yaml
	aws cloudformation wait stack-create-complete --stack-name $(CLUSTER_NAME)-efs

.PHONY: efs-id
efs-id:
	set -euo pipefail
	EFS_ID=$$(aws efs describe-file-systems --query "FileSystems[?Tags[?Key=='Name' && Value=='$(CLUSTER_NAME)-efs']].FileSystemId" --output text)
	if [ -z "$$EFS_ID" ]; then echo "No EFS ID found."; exit 1; fi
	echo "EFS ID: $$EFS_ID"

#===================#
# External Secrets  #
#===================#
.PHONY: eso
eso:
	set -euo pipefail
	echo "Setting up External Secrets Operator…"
	helm repo add external-secrets https://charts.external-secrets.io
	helm repo update
	helm upgrade --install external-secrets external-secrets/external-secrets \
	  --namespace $(APP_NS) \
	  --set controller.serviceAccount.create=false \
	  --set controller.serviceAccount.name=external-secrets

#===================#
# ALB Controller    #
#===================#
.PHONY: alb
alb:
	set -euo pipefail
	echo "Installing AWS Load Balancer Controller CRDs…"
	kubectl create -k "github.com/aws/eks-charts/stable/aws-load-balancer-controller/crds?ref=master" || true
	for crd in ingressclassparams.elbv2.k8s.aws targetgroupbindings.elbv2.k8s.aws; do \
	  until kubectl get crd $$crd &>/dev/null; do echo "Waiting for CRD $$crd…"; sleep 1; done; \
	done
	sleep 10
	CLUSTER_INFO=$$(eksctl get cluster --name "$(CLUSTER_NAME)" --region "$(AWS_DEFAULT_REGION)" -o json)
	VPC_ID=$$(echo "$$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.VpcId')
	echo "Installing AWS Load Balancer Controller (VPC: $$VPC_ID)…"
	helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
	  -n $(ELB_NS) \
	  --set clusterName=$(CLUSTER_NAME) \
	  --set serviceAccount.create=false \
	  --set serviceAccount.name=aws-alb-ingress-controller \
	  --set region=$(AWS_DEFAULT_REGION) \
	  --set setvpcId=$$VPC_ID \
	  --set image.repository=602401143452.dkr.ecr.us-east-1.amazonaws.com/amazon/aws-load-balancer-controller
	kubectl wait deployment aws-load-balancer-controller -n $(ELB_NS) --for=condition=Available=true --timeout=120s
	sleep 15

#===================#
# RabbitMQ          #
#===================#
.PHONY: rabbit
rabbit:
	set -euo pipefail
	echo "📡 Installing RabbitMQ Operator…"
	kubectl create namespace rabbitmq-system || true
	helm repo add bitnami https://charts.bitnami.com/bitnami
	helm repo update
	helm upgrade --install rabbitmq-operator bitnami/rabbitmq-cluster-operator --namespace rabbitmq-system
	kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=rabbitmq-cluster-operator -n rabbitmq-system --timeout=60s
	echo "Waiting for RabbitmqCluster CRD registration…"
	while ! kubectl get crd rabbitmqclusters.rabbitmq.com >/dev/null 2>&1; do sleep 2; done
	echo "Creating RabbitMQ cluster…"
	kubectl apply -f rabbitmq/$(VERS)/rabbitmq-cluster.yaml

	if [ "$(VERS)" = "v2" ]; then
	  kubectl wait ingress/rabbitmq-mgmt-ingress --for=jsonpath='{.status.loadBalancer.ingress[0].hostname}' --timeout=180s
	  kubectl wait ingress/rabbitmq-msg-ingress  --for=jsonpath='{.status.loadBalancer.ingress[0].hostname}' --timeout=180s
	else
	  echo "⏳ Waiting for RabbitMQ LoadBalancer to become ready…"
	  for i in $$(seq 1 30); do \
	    rabbitmqmsgdns=$$(kubectl get svc my-rabbit -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo ""); \
	    if [ -n "$$rabbitmqmsgdns" ]; then break; fi; \
	    echo "🔄 Waiting… ($$i/30)"; sleep 10; \
	  done
	fi

	# Collect Rabbit info & create app secret
	if [ "$(VERS)" = "v2" ]; then
	  rabbitmqmsgdns=$$(kubectl get ingress/rabbitmq-msg-ingress -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
	else
	  rabbitmqmsgdns=$$(kubectl get svc my-rabbit -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
	fi
	rabbitusername=$$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.username}" | base64 --decode)
	rabbitpassword=$$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.password}" | base64 --decode)

	if [ "$(VERS)" = "v2" ]; then
	  aws ssm put-parameter --name "/$(CLUSTER_NAME)/rabbithost"     --value "/$$rabbitmqmsgdns" --type "SecureString" --overwrite
	  aws ssm put-parameter --name "/$(CLUSTER_NAME)/rabbitusername" --value "/$$rabbitusername" --type "SecureString" --overwrite
	  aws ssm put-parameter --name "/$(CLUSTER_NAME)/rabbitpassword" --value "/$$rabbitpassword" --type "SecureString" --overwrite
	fi

	echo "Copying rabbitmq secrets to app namespace $(APP_NS)…"
	kubectl get secret my-rabbit-default-user -n $(APP_NS) &>/dev/null && \
	  kubectl delete secret my-rabbit-default-user -n $(APP_NS) && \
	  echo "Giving deletion five seconds to register…" && sleep 5 || true
	kubectl create secret generic my-rabbit-default-user \
	  --from-literal=username="$$rabbitusername" \
	  --from-literal=password="$$rabbitpassword" \
	  --from-literal=hostdns="$$rabbitmqmsgdns" \
	  -n $(APP_NS)

	echo "Updating manifest namespaces…"
	sed -i "s/namespace:.*/namespace: $(APP_NS)/" manifests/$(VERS)/*

.PHONY: rabbit-info
rabbit-info:
	set -euo pipefail
	if [ "$(VERS)" = "v2" ]; then
	  rabbitmqmgmtdns=$$(kubectl get ingress/rabbitmq-mgmt-ingress -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
	  rabbitmqmsgdns=$$(kubectl get ingress/rabbitmq-msg-ingress  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
	  echo "RabbitMQ MGMT DNS: $$rabbitmqmgmtdns"
	  echo "RabbitMQ MSG  DNS: $$rabbitmqmsgdns"
	else
	  rabbitmqmsgdns=$$(kubectl get svc my-rabbit -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
	  echo "RabbitMQ MGMT DNS: $$rabbitmqmsgdns:15672"
	  echo "RabbitMQ MSG  DNS: $$rabbitmqmsgdns:5672"
	fi
	rabbitusername=$$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.username}" | base64 --decode)
	rabbitpassword=$$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.password}" | base64 --decode)
	echo "RabbitMQ Username: $$rabbitusername"
	echo "RabbitMQ Password: $$rabbitpassword"

#===================#
# Windows Component #
#===================#
.PHONY: windows
windows:
	set -euo pipefail
	# Cluster info
	CLUSTER_INFO=$$(eksctl get cluster --name "$(CLUSTER_NAME)" --region "$(AWS_DEFAULT_REGION)" -o json)
	VPC_ID=$$(echo "$$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.VpcId')
	SUBNET_ID_1=$$(echo "$$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.SubnetIds[]' | head -n 1)
	SG_ID=$$(aws ec2 describe-instances --filters "Name=tag:eks:cluster-name,Values=$(CLUSTER_NAME)" --query 'Reservations[*].Instances[*].SecurityGroups[*].GroupId' --output text | uniq)

	# Rabbit info
	if [ "$(VERS)" = "v2" ]; then
	  rabbitmqmsgdns=$$(kubectl get ingress/rabbitmq-msg-ingress -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
	else
	  rabbitmqmsgdns=$$(kubectl get svc my-rabbit -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
	fi
	rabbitusername=$$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.username}" | base64 --decode)
	rabbitpassword=$$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.password}" | base64 --decode)

	aws ssm put-parameter --name "/$(CLUSTER_NAME)/rabbithost"     --value "$$rabbitmqmsgdns" --type "SecureString" --overwrite
	aws ssm put-parameter --name "/$(CLUSTER_NAME)/rabbitusername" --value "$$rabbitusername"  --type "SecureString" --overwrite
	aws ssm put-parameter --name "/$(CLUSTER_NAME)/rabbitpassword" --value "$$rabbitpassword"  --type "SecureString" --overwrite

	aws cloudformation create-stack --stack-name $(APP_NS)-windows-ra-ec2 \
	  --template-body file://./eks/$(VERS)/windows-ppt/windows-ppt-cft.yaml \
	  --parameters \
	    ParameterKey=AmiId,ParameterValue=$(WINDOWS_AMI) \
	    ParameterKey=SecurityGroupId,ParameterValue=$$SG_ID \
	    ParameterKey=SubnetId,ParameterValue=$$SUBNET_ID_1 \
	    ParameterKey=KeyName,ParameterValue=$(KEY_NAME) \
	    ParameterKey=ClusterName,ParameterValue=$(CLUSTER_NAME) \
	    ParameterKey=VpcId,ParameterValue=$$VPC_ID \
	    ParameterKey=ScriptURL,ParameterValue=$(WINDOWS_SCRIPT_URL) \
	  --capabilities CAPABILITY_NAMED_IAM \
	  --region $(AWS_DEFAULT_REGION)

	instance_id=$$(aws ec2 describe-instances \
	  --filters "Name=tag:aws:cloudformation:stack-name,Values=$(APP_NS)-windows-ra-ec2" \
	  --query "Reservations[].Instances[].InstanceId" \
	  --output text)

	echo ""
	echo "To run the SSM document and PowerShell script on the instance, run:"
	echo 'aws ssm send-command --document-name "WindowsAgentSetupScript" \'
	echo "  --targets \"Key=instanceIds,Values=$$instance_id\" \\"
	echo "  --output text"
	echo ""

#===================#
# Copy Rabbit Creds #
#===================#
# Implements new_rabbit_creds.sh logic
.PHONY: creds
creds:
	@if [ -z "$(APP_NS)" ]; then echo "APP_NS is required: make creds APP_NS=<namespace>"; exit 1; fi
	set -euo pipefail
	rabbitusername=$$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.username}" | base64 --decode)
	rabbitpassword=$$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.password}" | base64 --decode)
	kubectl get secret my-rabbit-default-user -n $(APP_NS) &>/dev/null && \
	  kubectl delete secret my-rabbit-default-user -n $(APP_NS) && \
	  echo "Giving deletion five seconds to register…" && sleep 5 || true
	echo "Recreating secrets in $(APP_NS) namespace…"
	kubectl create secret generic my-rabbit-default-user \
	  --from-literal=username="$$rabbitusername" \
	  --from-literal=password="$$rabbitpassword" \
	  -n $(APP_NS)

#===================#
# Teardown          #
#===================#
.PHONY: down
down:
	@$(require_vers)
	set -euo pipefail
	export AWS_DEFAULT_REGION=$(AWS_DEFAULT_REGION)
	# App manifests
	kubectl delete -f manifests/$(VERS) || true
	# Rabbit cluster
	kubectl delete -f rabbitmq/$(VERS)/rabbitmq-cluster.yaml || true
	# Windows EC2 stack
	aws cloudformation delete-stack --stack-name $(APP_NS)-windows-ra-ec2 || true
	# EFS stack
	aws cloudformation delete-stack --stack-name $(CLUSTER_NAME)-efs || true
	# IAM role stack
	aws cloudformation delete-stack --stack-name eks-addon-roles || true
	# Cluster
	eksctl delete cluster $(CLUSTER_NAME)

#===================#
# tmux              #
#===================#
# -------- tmux log dashboard --------
TMUX_SESSION ?= logs
LOG_SINCE    ?= 10m
APP_NS       ?= $(APP_NS)     # reuse your existing APP_NS; or set here

# Pick any 3 things to watch. These can be Kubernetes resources, shell commands, etc.
# By default I assume k8s Deployments; swap the commands if you want Pods/StatefulSets/containers.
SVC1 ?= ppt-upload-service
SVC2 ?= ppt-downloader-service
SVC3 ?= tts-processor-service
SVC4 ?= video-producer-service 

# If you want to point at specific containers in a multi-container pod, set CONTAINER1..3
CONTAINER1 ?=
CONTAINER2 ?=
CONTAINER3 ?=
CONTAINER4 ?=

# Compose the actual commands. Replace with whatever you like (docker logs, journalctl, etc).
LOGCMD1 ?= kubectl logs -n $(APP_NS) -f deployment/$(SVC1) $(if $(CONTAINER1),-c $(CONTAINER1),) --since=$(LOG_SINCE)
LOGCMD2 ?= kubectl logs -n $(APP_NS) -f deployment/$(SVC2) $(if $(CONTAINER2),-c $(CONTAINER2),) --since=$(LOG_SINCE)
LOGCMD3 ?= kubectl logs -n $(APP_NS) -f deployment/$(SVC3) $(if $(CONTAINER3),-c $(CONTAINER3),) --since=$(LOG_SINCE)
LOGCMD4 ?= kubectl logs -n $(APP_NS) -f deployment/$(SVC4) $(if $(CONTAINER4),-c $(CONTAINER4),) --since=$(LOG_SINCE)

.PHONY: tmux-logs
tmux-logs:
	@command -v tmux >/dev/null || { echo "tmux not found in PATH"; exit 1; }
	# Start detached session with the first command
	tmux new-session -d -s $(TMUX_SESSION) '$(LOGCMD1)'
	# Split horizontally into equal thirds
	tmux split-window -h -t $(TMUX_SESSION):0          '$(LOGCMD2)'         # make right column
	tmux split-window -v -t $(TMUX_SESSION):0.0        '$(LOGCMD3)'         # split left column
	tmux split-window -v -t $(TMUX_SESSION):0.1        '$(LOGCMD4)'         # split right column
	# Force layout to even-horizontal (all stacked, equal height)
	tmux select-layout -t $(TMUX_SESSION):0 tiled
	# Optional: clear scrollback in each pane for a fresh start
	#tmux send-keys -t $(TMUX_SESSION):0.0 C-l
	#tmux send-keys -t $(TMUX_SESSION):0.1 C-l
	#tmux send-keys -t $(TMUX_SESSION):0.2 C-l
	# Optional: set a nice status and synchronize off
	tmux set-option -t $(TMUX_SESSION) -g status on
	tmux set-window-option -t $(TMUX_SESSION):0 synchronize-panes off
	# Attach
	tmux attach -t $(TMUX_SESSION)

.PHONY: tmux-logs-reattach
tmux-logs-reattach:
	@tmux attach -t $(TMUX_SESSION)

.PHONY: tmux-logs-kill
tmux-logs-kill:
	@tmux kill-session -t $(TMUX_SESSION) 2>/dev/null || true
	@echo "Killed tmux session: $(TMUX_SESSION)"
