#!/bin/bash
set -euo pipefail

###############################################################
## Specify these details
AWS_ACCT="228122752878"
cluster_name="event-driven-poc"
app_namespace="event-poc"
export AWS_DEFAULT_REGION=us-east-1
windows_ami="ami-02b60b5095d1e5227"   # Latest windows base 2025
key_name="fgt-kp"
###############################################################

VERS=$1

if [ $# -eq 0 ] || [ $# -gt 1 ]; then
  echo "Zero or too many arguments supplied..."
  echo "Example: ./create-scripts/create-cluster.sh v1"
  exit 1
fi

echo "Launching $VERS setup...."

eksctl create cluster -f eks/${VERS}/event-poc-cluster.yaml
kubectl create namespace $app_namespace
kubectl create namespace aws-elb-controller-namespace

eksctl utils associate-iam-oidc-provider --cluster event-driven-poc --approve
OIDCId=$(aws eks describe-cluster --name $cluster_name --query "cluster.identity.oidc.issuer" --output text | cut -d'/' -f5)

CLUSTER_INFO=$(eksctl get cluster --name "$cluster_name" --region "$AWS_DEFAULT_REGION" -o json)
VPC_ID=$(echo "$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.VpcId')
SUBNET_IDS=$(echo "$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.SubnetIds[]' | head -n 2)
SUBNET_ID_1=$(echo "$SUBNET_IDS" | sed -n '1p')
SUBNET_ID_2=$(echo "$SUBNET_IDS" | sed -n '2p')
SG_ID=$(aws ec2 describe-instances --filters "Name=tag:eks:cluster-name,Values=$cluster_name" --query 'Reservations[*].Instances[*].SecurityGroups[*].GroupId' --output text | uniq)

aws cloudformation create-stack --stack-name eks-addon-roles   \
    --template-body file://./iam/${VERS}/sa-roles-cft.yml   \
    --parameters       \
        ParameterKey=ClusterName,ParameterValue=event-driven-poc       \
        ParameterKey=OIDCId,ParameterValue=$OIDCId   \
        ParameterKey=Namespace,ParameterValue=$app_namespace \
    --capabilities CAPABILITY_NAMED_IAM   \
    --region $AWS_DEFAULT_REGION

echo "⏳  Waiting for SA roles..."
aws cloudformation wait stack-create-complete --stack-name eks-addon-roles

for i in {1..30}; do
  EFSCSIrole=$(aws cloudformation describe-stacks --stack-name eks-addon-roles --query "Stacks[0].Outputs[?OutputKey=='EFSCSIRoleArn'].OutputValue" --output text)
  if [[ -n "$EFSCSIrole" ]]; then
    break
  fi
  echo "🔄 Waiting for EFSCSIrole... ($i/30)"
  sleep 10
done

for i in {1..30}; do
  ESOrole=$(aws cloudformation describe-stacks --stack-name eks-addon-roles --query "Stacks[0].Outputs[?OutputKey=='ESORoleArn'].OutputValue" --output text)
  if [[ -n "$ESOrole" ]]; then
    break
  fi
  echo "🔄 Waiting for ESOrole... ($i/30)"
  sleep 10
done

for i in {1..30}; do
  ALBIngressrole=$(aws cloudformation describe-stacks --stack-name eks-addon-roles --query "Stacks[0].Outputs[?OutputKey=='ALBIngressRoleArn'].OutputValue" --output text)
  if [[ -n "$ALBIngressrole" ]]; then
    break
  fi
  echo "🔄 Waiting for ESOrole... ($i/30)"
  sleep 10
done

echo "Created roles: "
echo $EFSCSIrole
echo $ESOrole
echo $ALBIngressrole

sed -i "s/^\(\s*namespace:\s*\).*/\1${app_namespace}/" eks/${VERS}/service-accounts/sa.yml
sed -i "/name: efs-csi-controller-sa/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $EFSCSIrole#" eks/${VERS}/service-accounts/sa.yml
sed -i "/name: eso-sa/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $ESOrole#" eks/${VERS}/service-accounts/sa.yml
sed -i "/name: aws-alb-ingress-controller/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $ALBIngressrole#" eks/${VERS}/service-accounts/sa.yml
sed -i "/name: aws-alb-ingress-controller/,/namespace:/ s#^\([[:space:]]*namespace:\).*#\1 aws-elb-controller-namespace#" eks/${VERS}/service-accounts/sa.yml

kubectl create -f eks/${VERS}/service-accounts/sa.yml

echo "📦 Installing EFS CSI driver add-on..."
eksctl create addon \
  --cluster "$cluster_name" \
  --name aws-efs-csi-driver \
  --version latest \
  --service-account-role-arn $EFSCSIrole \
  --force

echo "💾 Creating EFS filesystem..."
sed -i "s/CLUSTER_NAME=.*/CLUSTER_NAME=\"$cluster_name\"/" eks/${VERS}/efs/create-efs.sh
./eks/${VERS}/efs/create-efs.sh ${VERS}

echo "Creating Shared Artifacts PVC for apps..."
sed -i "s/namespace=.*/namespace=\"$cluster_name\"/" eks/${VERS}/storage/shared-artifacts-pvc.yaml
kubectl create -f eks/${VERS}/storage/shared-artifacts-pvc.yaml

echo "⏳  Waiting for EFS..."
for i in {1..30}; do
  EFS_ID=$(aws efs describe-file-systems --query "FileSystems[?Tags[?Key=='Name' && Value=='$cluster_name-efs']].FileSystemId" --output text)
  if [[ -n "$EFS_ID" ]]; then
    break
  fi
  echo "🔄 Waiting... ($i/30)"
  sleep 10
done

echo "📄 Patching StorageClass with EFS ID: $EFS_ID"
sed -i "s/fileSystemId: .*/fileSystemId: $EFS_ID/" eks/${VERS}/efs/efs-sc.yaml
kubectl create -f eks/${VERS}/efs/efs-sc.yaml
aws cloudformation wait stack-create-complete --stack-name $cluster_name-efs

echo "Setting up external secrets operator...."
helm repo add external-secrets https://charts.external-secrets.io
helm repo update

helm upgrade --install external-secrets external-secrets/external-secrets \
  --namespace $app_namespace \
  --set controller.serviceAccount.create=false \
  --set controller.serviceAccount.name=external-secrets

set -x
if [[ "${VERS}" == "v2" ]]; then
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
    echo "CRD $crd is available."
  done

  echo "Sleeping to give it a few extra seconds..."
  sleep 10

  helm install aws-load-balancer-controller eks/aws-load-balancer-controller  \
    -n aws-elb-controller-namespace   \
    --set clusterName=event-driven-poc   \
    --set serviceAccount.create=false   \
    --set serviceAccount.name=aws-alb-ingress-controller   \
    --set region=$AWS_DEFAULT_REGION   \
    --set setvpcId=$VPC_ID   \
    --set image.repository=602401143452.dkr.ecr.us-east-1.amazonaws.com/amazon/aws-load-balancer-controller
  sleep 5
  kubectl wait deployment aws-load-balancer-controller \
    -n aws-elb-controller-namespace \
    --for=condition=Available=true \
    --timeout=120s
  sleep 15
fi

echo "📡 Installing RabbitMQ Operator..."
kubectl create namespace rabbitmq-system
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update
helm install rabbitmq-operator bitnami/rabbitmq-cluster-operator --namespace rabbitmq-system
kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=rabbitmq-cluster-operator -n rabbitmq-system --timeout=60s

echo "Waiting for RabbitmqCluster to be registered..."
while ! kubectl get crd rabbitmqclusters.rabbitmq.com >/dev/null 2>&1; do
  sleep 2
done
echo "RabbitmqCluster CRD ready, proceeding to deploy..."

sleep 30

echo "Creating rabbitmq cluster..."
kubectl apply -f rabbitmq/${VERS}/rabbitmq-cluster.yaml

echo "⏳  Waiting for RabbitMQ LoadBalancer to become ready..."
for i in {1..30}; do
  rabbit_host=$(kubectl get svc my-rabbit -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
  if [[ -n "$rabbit_host" ]]; then
    break
  fi
  echo "🔄 Waiting... ($i/30)"
  sleep 10
done

if [[ -z "$rabbit_host" ]]; then
  echo "❌  RabbitMQ LoadBalancer hostname not found after 5 minutes."
  exit 1
fi

rabbitmqdns="http://$rabbit_host:15672"
echo "🌐 RabbitMQ URL: $rabbitmqdns"

rabbitusername=$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.username}" | base64 --decode)
rabbitpassword=$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.password}" | base64 --decode)

if [[ "${VERS}" == "v2" ]]; then
  # Note we're using yq below--if you're default output format is json, use jq
  rabbitmqnlbdns=$(aws elbv2 describe-load-balancers \
    --query "LoadBalancers[?Type=='network'].LoadBalancerArn" \
    --output text | \
    xargs -n 1 aws elbv2 describe-tags --resource-arns | \
    yq -r '.TagDescriptions[] | select(.Tags[]? | select(.Key=="service.k8s.aws/stack" and .Value=="default/my-rabbit")) | .ResourceArn' | \
    xargs -n 1 aws elbv2 describe-load-balancers --load-balancer-arns | \
    yq -r '.LoadBalancers[].DNSName')
  aws ssm put-parameter \
    --name "/$cluster_name/rabbithost" \
    --value "/$rabbitmqnlbdns" \
    --type "SecureString" \
    --overwrite
  aws ssm put-parameter \
    --name "/$cluster_name/rabbitusername" \
    --value "/$rabbitusername" \
    --type "SecureString" \
    --overwrite
  aws ssm put-parameter \
    --name "/$cluster_name/rabbitpassword" \
    --value "/$rabbitusername" \
    --type "SecureString" \
    --overwrite

#  aws cloudformation create-stack --stack-name $app_namespace-windows-ra-ec2 \
#      --template-body file://./eks/${VERS}/windows-ppt/windows-ppt-cft.yaml  \
#      --parameters       \
#          ParameterKey=AmiId,ParameterValue=$windows_ami       \
#          ParameterKey=SecurityGroupId,ParameterValue=$SG_ID   \
#          ParameterKey=SubnetId,ParameterValue=$SUBNET_ID_1 \
#          ParameterKey=KeyName,ParameterValue=$key_name \
#          ParameterKey=NFSDNS,ParameterValue=$rabbitmqnlbdns \
#          ParameterKey=ClusterName,ParameterValue=$cluster_name \
#      --capabilities CAPABILITY_NAMED_IAM   \
#      --region $AWS_DEFAULT_REGION
fi

echo "Copying rabbitmq secrets to app namespace:"
echo "📁 Creating app namespace..."
kubectl create secret generic my-rabbit-default-user \
  --from-literal=username="$rabbitusername" \
  --from-literal=password="$rabbitpassword" \
  --from-literal=hostdns="$rabbitmqnlbdns" \
  -n $app_namespace

echo "Updating manifest namespaces..."
sed -i "s/namespace:.*/namespace: $app_namespace/" manifests/${VERS}/*
echo "RabbitMQ UI can be acccessed here: http://$rabbitmqnlbdns"
echo "RabbitMQ Username: $rabbitusername"
echo "RabbitMQ Password: $rabbitpassword"
echo ""
echo "Run 'kubectl create -f manifests/${VERS}/' to deploy POC.'"
