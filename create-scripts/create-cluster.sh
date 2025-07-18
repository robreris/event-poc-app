#!/bin/bash
set -euo pipefail

#===================#
# Config Variables  #
#===================#
export AWS_ACCT="228122752878"
export AWS_DEFAULT_REGION=us-east-1

cluster_name="event-driven-poc"
app_namespace="event-poc"
elb_controller_namespace="aws-elb-controller-namespace"
windows_ami="ami-02b60b5095d1e5227"
windows_script_url="https://raw.githubusercontent.com/robreris/event-poc-app/refs/heads/main/eks/v2/windows-ppt/windows-userdata.ps1"
key_name="fgt-kp"

VERS=$1

#===================#
# Usage Check       #
#===================#
check_args() {
  if [ $# -eq 0 ] || [ $# -gt 1 ]; then
    echo "Zero or too many arguments supplied..."
    echo "Example: ./create-scripts/create-cluster.sh v1"
    exit 1
  fi
  echo "Launching $VERS setup...."
}

#===================#
# Cluster Setup     #
#===================#
create_cluster() {
  eksctl create cluster -f eks/${VERS}/event-poc-cluster.yaml
  kubectl create namespace $app_namespace
  kubectl create namespace $elb_controller_namespace
  get_cluster_info
}

#===================#
# Get Cluster Info  #
#===================#
get_cluster_info() {
  declare -g CLUSTER_INFO=$(eksctl get cluster --name "$cluster_name" --region "$AWS_DEFAULT_REGION" -o json)
  declare -g VPC_ID=$(echo "$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.VpcId')
  declare -g SUBNET_IDS=$(echo "$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.SubnetIds[]' | head -n 2)
  declare -g SUBNET_ID_1=$(echo "$SUBNET_IDS" | sed -n '1p')
  declare -g SUBNET_ID_2=$(echo "$SUBNET_IDS" | sed -n '2p')
  declare -g SG_ID=$(aws ec2 describe-instances --filters "Name=tag:eks:cluster-name,Values=$cluster_name" --query 'Reservations[*].Instances[*].SecurityGroups[*].GroupId' --output text | uniq)
  echo "#### Cluster VPC Info ###"
  echo "VPC Id: $VPC_ID"
  echo "Subnet ID 1: $SUBNET_ID_1"
  echo "Subnet ID 2: $SUBNET_ID_2"
  echo "Cluster Security Group: $SG_ID"
}


#===================#
# IAM/OIDC Setup    #
#===================#
setup_oidc_and_roles() {
  eksctl utils associate-iam-oidc-provider --cluster "$cluster_name" --approve
  get_oidc_id

  aws cloudformation create-stack --stack-name eks-addon-roles \
    --template-body file://./iam/${VERS}/sa-roles-cft.yml \
    --parameters \
      ParameterKey=ClusterName,ParameterValue=$cluster_name \
      ParameterKey=OIDCId,ParameterValue=$OIDCId \
      ParameterKey=Namespace,ParameterValue=$app_namespace \
    --capabilities CAPABILITY_NAMED_IAM \
    --region $AWS_DEFAULT_REGION

  echo "⏳  Waiting for SA roles..."
  aws cloudformation wait stack-create-complete --stack-name eks-addon-roles
}


#=====================#
# Retrieve OIDC ID    #
#=====================#
get_oidc_id() {
  declare -g OIDCId=$(aws eks describe-cluster --name $cluster_name --query "cluster.identity.oidc.issuer" --output text | cut -d'/' -f5)
  if [[ "$OIDCId" == "" ]]; then
    echo "OIDC Id not found."
  else 
    echo "OIDC ID: $OIDCId"
  fi
}

#===========================#
# Extract IAM Role Outputs #
#===========================#
extract_iam_roles() {
  for role_key in EFSCSIRoleArn ESORoleArn ALBIngressRoleArn FrontendS3RoleArn; do
    for i in {1..30}; do
      role_value=$(aws cloudformation describe-stacks --stack-name eks-addon-roles --query "Stacks[0].Outputs[?OutputKey=='$role_key'].OutputValue" --output text)
      if [[ -n "$role_value" ]]; then
        declare -g "$role_key"="$role_value"
        break
      fi
      echo "🔄 Waiting for $role_value... ($i/30)"
      sleep 10
    done
  done

  echo "Created roles:"
  echo $EFSCSIRoleArn
  echo $ESORoleArn
  echo $ALBIngressRoleArn
  echo $FrontendS3RoleArn
}

#============================#
# Update and Apply SA YAML  #
#============================#
configure_service_accounts() {

  sed -i "s/^\(\s*namespace:\s*\).*/\1${app_namespace}/" eks/${VERS}/service-accounts/sa.yml
  sed -i "/name: efs-csi-controller-sa/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $EFSCSIRoleArn#" eks/${VERS}/service-accounts/sa.yml
  sed -i "/name: eso-sa/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $ESORoleArn#" eks/${VERS}/service-accounts/sa.yml
  sed -i "/name: frontend-s3-sa/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $FrontendS3RoleArn#" eks/${VERS}/service-accounts/sa.yml
  sed -i "/name: aws-alb-ingress-controller/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $ALBIngressRoleArn#" eks/${VERS}/service-accounts/sa.yml
  sed -i "/name: aws-alb-ingress-controller/,/namespace:/ s#^\([[:space:]]*namespace:\).*#\1 $elb_controller_namespace#" eks/${VERS}/service-accounts/sa.yml

  kubectl create -f eks/${VERS}/service-accounts/sa.yml
}

#====================#
# EFS + PVC Setup    #
#====================#
setup_efs() {
  echo "📦 Installing EFS CSI driver add-on..."
  echo "Using role: $EFSCSIRoleArn"
  eksctl create addon \
    --cluster "$cluster_name" \
    --name aws-efs-csi-driver \
    --version latest \
    --service-account-role-arn $EFSCSIRoleArn \
    --force

  echo "💾 Creating EFS filesystem..."
  sed -i "s/CLUSTER_NAME=.*/CLUSTER_NAME=\"$cluster_name\"/" eks/${VERS}/efs/create-efs.sh
  ./eks/${VERS}/efs/create-efs.sh ${VERS}

  echo "Creating Shared Artifacts PVC for apps..."
  sed -i "s/namespace=.*/namespace=\"$cluster_name\"/" eks/${VERS}/storage/shared-artifacts-pvc.yaml
  kubectl create -f eks/${VERS}/storage/shared-artifacts-pvc.yaml

  echo "⏳  Waiting for EFS..."
  for i in {1..30}; do
    declare -g EFS_ID=$(aws efs describe-file-systems --query "FileSystems[?Tags[?Key=='Name' && Value=='$cluster_name-efs']].FileSystemId" --output text)
    if [[ -n "$EFS_ID" ]]; then break; fi
    echo "🔄 Waiting... ($i/30)"
    sleep 10
  done

  echo "📄 Patching StorageClass with EFS ID: $EFS_ID"
  sed -i "s/fileSystemId: .*/fileSystemId: $EFS_ID/" eks/${VERS}/efs/efs-sc.yaml
  kubectl create -f eks/${VERS}/efs/efs-sc.yaml
  aws cloudformation wait stack-create-complete --stack-name $cluster_name-efs
}

#==================#
# Retrieve EFS_ID  #
#==================#
get_efs_id() {
    declare -g EFS_ID=$(aws efs describe-file-systems --query "FileSystems[?Tags[?Key=='Name' && Value=='$cluster_name-efs']].FileSystemId" --output text)
    if [[ "$EFS_ID" == "" ]]; then
       echo "No EFS ID found."
    else
       echo "EFS ID: $EFS_ID"
    fi
}

#=============================#
# External Secrets Operator  #
#=============================#
setup_external_secrets() {
  echo "Setting up external secrets operator...."
  helm repo add external-secrets https://charts.external-secrets.io
  helm repo update

  helm upgrade --install external-secrets external-secrets/external-secrets \
    --namespace $app_namespace \
    --set controller.serviceAccount.create=false \
    --set controller.serviceAccount.name=external-secrets
}

#=============================#
# Load Balancer Controller   #
#=============================#
install_lb_controller() {
  echo "Installing AWS load balancer controller helm chart..."

  required_crds=(
    ingressclassparams.elbv2.k8s.aws
    targetgroupbindings.elbv2.k8s.aws
  )

  echo "Deploying and waiting for aws lb controller CRDs to be ready..."
  kubectl create -k "github.com/aws/eks-charts/stable/aws-load-balancer-controller/crds?ref=master"
  for crd in "${required_crds[@]}"; do
    until kubectl get crd "$crd" &> /dev/null; do
      echo "Waiting for CRD $crd..."
      sleep 1
    done
  done

  sleep 10

  helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
    -n $elb_controller_namespace \
    --set clusterName=$cluster_name \
    --set serviceAccount.create=false \
    --set serviceAccount.name=aws-alb-ingress-controller \
    --set region=$AWS_DEFAULT_REGION \
    --set setvpcId=$VPC_ID \
    --set image.repository=602401143452.dkr.ecr.us-east-1.amazonaws.com/amazon/aws-load-balancer-controller

  kubectl wait deployment aws-load-balancer-controller -n $elb_controller_namespace --for=condition=Available=true --timeout=120s
  sleep 15
}

#=====================#
# RabbitMQ Setup      #
#=====================#
install_rabbitmq() {
  echo "📡 Installing RabbitMQ Operator..."
  kubectl create namespace rabbitmq-system
  helm repo add bitnami https://charts.bitnami.com/bitnami
  helm repo update
  helm install rabbitmq-operator bitnami/rabbitmq-cluster-operator --namespace rabbitmq-system
  kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=rabbitmq-cluster-operator -n rabbitmq-system --timeout=60s

  echo "Waiting for RabbitmqCluster to be registered..."
  while ! kubectl get crd rabbitmqclusters.rabbitmq.com >/dev/null 2>&1; do sleep 2; done

  echo "Creating rabbitmq cluster..."
  kubectl apply -f rabbitmq/${VERS}/rabbitmq-cluster.yaml
  if [[ "${VERS}" == "v2" ]]; then
    kubectl wait ingress/rabbitmq-mgmt-ingress --for=jsonpath='{.status.loadBalancer.ingress[0].hostname}' --timeout=180s
    kubectl wait ingress/rabbitmq-msg-ingress --for=jsonpath='{.status.loadBalancer.ingress[0].hostname}' --timeout=180s
  else
    echo "⏳ Waiting for RabbitMQ LoadBalancer to become ready..."
    for i in {1..30}; do
      rabbitmqmsgdns=$(kubectl get svc my-rabbit -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
      if [[ -n "$rabbitmqmsgdns" ]]; then
        break
      fi
      echo "🔄 Waiting... ($i/30)"
      sleep 10
    done
  fi

  get_rabbit_info

  if [[ "${VERS}" == "v2" ]]; then
    aws ssm put-parameter --name "/$cluster_name/rabbithost" --value "/$rabbitmqmsgdns" --type "SecureString" --overwrite
    aws ssm put-parameter --name "/$cluster_name/rabbitusername" --value "/$rabbitusername" --type "SecureString" --overwrite
    aws ssm put-parameter --name "/$cluster_name/rabbitpassword" --value "/$rabbitpassword" --type "SecureString" --overwrite
  fi

  echo "Copying rabbitmq secrets to app namespace..."
  kubectl create secret generic my-rabbit-default-user \
    --from-literal=username="$rabbitusername" \
    --from-literal=password="$rabbitpassword" \
    --from-literal=hostdns="$rabbitmqmsgdns" \
    -n $app_namespace

  echo "Updating manifest namespaces..."
  sed -i "s/namespace:.*/namespace: $app_namespace/" manifests/${VERS}/*
}


#======================#
# Return RabbitMQ Info #
#======================#
get_rabbit_info() {  

  if [[ "${VERS}" == "v2" ]]; then
    declare -g rabbitmqmgmtdns=$(kubectl get ingress/rabbitmq-mgmt-ingress -o jsonpath='{.status.loadBalancer.ingress[0].hostname}') 
    declare -g rabbitmqmsgdns=$(kubectl get ingress/rabbitmq-msg-ingress -o jsonpath='{.status.loadBalancer.ingress[0].hostname}') 
    echo "RabbitMQ MGMT DNS: $rabbitmqmgmtdns"
    echo "RabbitMQ MSG DNS: $rabbitmqmsgdns"
  else
    declare -g rabbitmqmsgdns=$(kubectl get svc my-rabbit -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
    echo "RabbitMQ MGMT DNS: $rabbitmqmsgdns:15672"
    echo "RabbitMQ MSG DNS: $rabbitmqmsgdns:5672"
  fi

  declare -g rabbitusername=$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.username}" | base64 --decode)
  declare -g rabbitpassword=$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.password}" | base64 --decode)
  echo "RabbitMQ Username: $rabbitusername"
  echo "RabbitMQ Password: $rabbitpassword"
}


#=====================#
# Windows EC2 Setup   #
#=====================#
create_windows_component() {

  get_rabbit_info

  aws ssm put-parameter \
    --name "/$cluster_name/rabbithost" \
    --value "$rabbitmqmsgdns" \
    --type "SecureString" \
    --overwrite

  aws ssm put-parameter \
    --name "/$cluster_name/rabbitusername" \
    --value "$rabbitusername" \
    --type "SecureString" \
    --overwrite

  aws ssm put-parameter \
    --name "/$cluster_name/rabbitpassword" \
    --value "$rabbitpassword" \
    --type "SecureString" \
    --overwrite

  aws cloudformation create-stack --stack-name $app_namespace-windows-ra-ec2 \
      --template-body file://./eks/${VERS}/windows-ppt/windows-ppt-cft.yaml  \
      --parameters       \
          ParameterKey=AmiId,ParameterValue=$windows_ami       \
          ParameterKey=SecurityGroupId,ParameterValue=$SG_ID   \
          ParameterKey=SubnetId,ParameterValue=$SUBNET_ID_1 \
          ParameterKey=KeyName,ParameterValue=$key_name \
          ParameterKey=ClusterName,ParameterValue=$cluster_name \
          ParameterKey=VpcId,ParameterValue=$VPC_ID \
          ParameterKey=ScriptURL,ParameterValue=$windows_script_url\
      --capabilities CAPABILITY_NAMED_IAM   \
      --region $AWS_DEFAULT_REGION

  instance_id=$(aws ec2 describe-instances \
    --filters "Name=tag:aws:cloudformation:stack-name,Values=event-poc-windows-ra-ec2" \
    --query "Reservations[].Instances[].InstanceId" \
    --output text)

  echo "To run the SSM document and the powershell script on the instance, run:"
  echo "aws ssm send-command --document-name \"WindowsAgentSetupScript\" \\"
  echo "  --targets \"Key=instanceIds,Values=$instance_id\" \\"
  echo "  --output text"

}


#=====================#
# Execution Control   #
#=====================#
main() {

  # set up cluster
  check_args "$@"
  create_cluster
  get_cluster_info

  setup_oidc_and_roles
  get_oidc_id
  extract_iam_roles
  configure_service_accounts

  setup_efs
  get_efs_id
  setup_external_secrets

  #if [[ "${VERS}" == "v2" ]]; then
  #  install_lb_controller
  #fi
  install_rabbitmq
  get_rabbit_info

  #if [[ "${VERS}" == "v2" ]]; then
  #  create_windows_component
  #fi

}

main "$@"

