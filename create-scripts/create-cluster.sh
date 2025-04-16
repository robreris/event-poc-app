#!/bin/bash
set -euo pipefail

AWS_ACCT="228122752878"  # Enter your account number here
cluster_name="event-driven-poc"
app_namespace="event-poc"
export AWS_DEFAULT_REGION=us-east-1

echo "🔧 Creating EKS cluster: "$cluster_name
sed -i "/^metadata:/,/^[^[:space:]]/s/^\([[:space:]]*name:[[:space:]]*\).*/\1$cluster_name/" eks/event-poc-cluster.yaml
eksctl create cluster -f eks/event-poc-cluster.yaml

role_name="AmazonEKS_EFS_CSI_DriverRole"

echo "🔐 Associating IAM OIDC provider..."
eksctl utils associate-iam-oidc-provider \
  --cluster "$cluster_name" \
  --approve

echo "🔐 Creating IAM service account (role only)..."
eksctl create iamserviceaccount  \
  --name efs-csi-controller-sa   \
  --namespace kube-system   \
  --cluster "$cluster_name"  \
  --role-name "$role_name"  \
  --role-only   \
  --attach-policy-arn arn:aws:iam::aws:policy/service-role/AmazonEFSCSIDriverPolicy  \
  --approve

echo "🔄 Updating trust policy..."
TRUST_POLICY=$(aws iam get-role --output json --role-name "$role_name" --query 'Role.AssumeRolePolicyDocument' | \
    sed -e 's/efs-csi-controller-sa/efs-csi-*/' -e 's/StringEquals/StringLike/')

aws iam update-assume-role-policy --role-name "$role_name" --policy-document "$TRUST_POLICY"

echo "📦 Installing EFS CSI driver add-on..."
eksctl create addon \
  --cluster "$cluster_name" \
  --name aws-efs-csi-driver \
  --version latest \
  --service-account-role-arn arn:aws:iam::$AWS_ACCT:role/$role_name \
  --force

echo "💾 Creating EFS filesystem..."
sed -i "s/CLUSTER_NAME=.*/CLUSTER_NAME=\"$cluster_name\"/" eks/infra/create-efs.sh
./eks/infra/create-efs.sh

sleep 30

echo "⏳ Waiting for EFS..."
for i in {1..30}; do
  EFS_ID=$(aws efs describe-file-systems --query "FileSystems[?Tags[?Key=='Name' && Value=='$cluster_name-efs']].FileSystemId" --output text)
  if [[ -n "$EFS_ID" ]]; then
    break
  fi
  echo "🔄 Waiting... ($i/30)"
  sleep 10
done

echo "📄 Patching StorageClass with EFS ID: $EFS_ID"
sed -i "s/fileSystemId: .*/fileSystemId: $EFS_ID/" eks/infra/efs-sc.yaml
kubectl create -f eks/infra/efs-sc.yaml

echo "📡 Installing RabbitMQ Operator..."
kubectl create namespace rabbitmq-system
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update
helm install rabbitmq-operator bitnami/rabbitmq-cluster-operator --namespace rabbitmq-system
kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=rabbitmq-cluster-operator -n rabbitmq-system --timeout=60s
kubectl apply -f rabbitmq/rabbitmq-cluster.yaml

echo "⏳ Waiting for RabbitMQ LoadBalancer to become ready..."
for i in {1..30}; do
  rabbit_host=$(kubectl get svc my-rabbit -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
  if [[ -n "$rabbit_host" ]]; then
    break
  fi
  echo "🔄 Waiting... ($i/30)"
  sleep 10
done

if [[ -z "$rabbit_host" ]]; then
  echo "❌ RabbitMQ LoadBalancer hostname not found after 5 minutes."
  exit 1
fi

rabbitmqdns="http://$rabbit_host:15672"
echo "🌐 RabbitMQ URL: $rabbitmqdns"

rabbitusername=$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.username}" | base64 --decode)
rabbitpassword=$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.password}" | base64 --decode)


echo "📁 Creating app namespace..."
kubectl create namespace $app_namespace
kubectl create secret generic my-rabbit-default-user \
  --from-literal=username="$rabbitusername" \
  --from-literal=password="$rabbitpassword" \
  -n $app_namespace
find k8s -type f -name '*.yaml' -exec sed -i "s/namespace:.*/namespace: $cluster_name/" {} +

echo "Cluster created, ready to build images, push to ECR, and deploy."

#echo "🚀 Deploying app..."
#kubectl create -f k8s/pvc.yaml
#kubectl create -f k8s/deployments/
