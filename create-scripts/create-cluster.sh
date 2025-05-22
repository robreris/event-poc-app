#!/bin/bash
set -euo pipefail

###############################################################
## Specify these details
AWS_ACCT="228122752878"
cluster_name="event-driven-poc"
app_namespace="event-poc"
export AWS_DEFAULT_REGION=us-east-1
###############################################################

eksctl create cluster -f eks/event-poc-cluster.yaml
kubectl create namespace $app_namespace

eksctl utils associate-iam-oidc-provider --cluster event-driven-poc --approve
OIDCId=$(aws eks describe-cluster --name $cluster_name --query "cluster.identity.oidc.issuer" --output text | cut -d'/' -f5)

aws cloudformation create-stack --stack-name eks-addon-roles   \
    --template-body file://./iam/sa-roles-cft.yml   \
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

sed -i "s/^\(\s*namespace:\s*\).*/\1${app_namespace}/" eks/service-accounts/sa.yml
sed -i "/name: efs-csi-controller-sa/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $EFSCSIrole#" eks/service-accounts/sa.yml
sed -i "/name: eso-sa/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $ESOrole#" eks/service-accounts/sa.yml
sed -i "/name: aws-alb-ingress-controller/,/eks.amazonaws.com\/role-arn:/ s#^\([[:space:]]*eks.amazonaws.com/role-arn:\).*#\1 $ALBIngressrole#" eks/service-accounts/sa.yml
kubectl create -f eks/service-accounts/sa.yml

echo "📦 Installing EFS CSI driver add-on..."
eksctl create addon \
  --cluster "$cluster_name" \
  --name aws-efs-csi-driver \
  --version latest \
  --service-account-role-arn $EFSCSIrole \
  --force

echo "💾 Creating EFS filesystem..."
sed -i "s/CLUSTER_NAME=.*/CLUSTER_NAME=\"$cluster_name\"/" eks/efs/create-efs.sh
./eks/efs/create-efs.sh

echo "Creating Shared Artifacts PVC for apps..."
sed -i "s/namespace=.*/namespace=\"$cluster_name\"/" eks/storage/shared-artifacts-pvc.yaml
kubectl create -f eks/storage/shared-artifacts-pvc.yaml

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
sed -i "s/fileSystemId: .*/fileSystemId: $EFS_ID/" eks/efs/efs-sc.yaml
kubectl create -f eks/efs/efs-sc.yaml

echo "Setting up external secrets operator...."
helm repo add external-secrets https://charts.external-secrets.io
helm repo update

helm upgrade --install external-secrets external-secrets/external-secrets \
  --namespace $app_namespace \
  --set controller.serviceAccount.create=false \
  --set controller.serviceAccount.name=external-secrets

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
kubectl apply -f rabbitmq/rabbitmq-cluster.yaml

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

echo "Copying rabbitmq secrets to app namespace:"
echo "📁 Creating app namespace..."
kubectl create secret generic my-rabbit-default-user \
  --from-literal=username="$rabbitusername" \
  --from-literal=password="$rabbitpassword" \
  -n $app_namespace

echo "Updating manifest namespaces..."
sed -i "s/namespace:.*/namespace: $app_namespace/" manifests/*
echo "RabbitMQ UI can be acccessed here: $rabbitmqdns"
echo "RabbitMQ Username: $rabbitusername"
echo "RabbitMQ Password: $rabbitpassword"
echo ""
echo "Run 'kubectl create -f manifests/' to deploy POC.'"
