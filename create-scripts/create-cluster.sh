#!/bin/bash
set -euo pipefail

AWS_ACCT="228122752878"  # Enter your account number here
cluster_name="event-driven-poc"
app_namespace="event-poc"
export AWS_DEFAULT_REGION=us-east-1

echo "🔧 Creating EKS cluster: "$cluster_name
sed -i "/^metadata:/,/^[^[:space:]]/s/^\([[:space:]]*name:[[:space:]]*\).*/\1$cluster_name/" eks/event-poc-cluster.yaml
eksctl create cluster -f eks/event-poc-cluster.yaml

role_name="AmazonEKS_EFS_CSI_DriverRole-$cluster_name"

echo "🔐 Associating IAM OIDC provider..."
eksctl utils associate-iam-oidc-provider \
  --cluster "$cluster_name" \
  --approve

echo "🔐 Creating IAM service account (role only)..."
eksctl create iamserviceaccount  \
  --name efs-csi-controller-sa-$cluster_name   \
  --namespace kube-system   \
  --cluster "$cluster_name"  \
  --role-name "$role_name"  \
  --role-only   \
  --attach-policy-arn arn:aws:iam::aws:policy/service-role/AmazonEFSCSIDriverPolicy  \
  --approve

echo "🔄 Updating trust policy..."
OIDC_ISSUER=$(aws eks describe-cluster --name "$cluster_name" --query "cluster.identity.oidc.issuer" --output text | sed -e "s/^https:\/\///")

cat > iam/efs-csi-trust-policy.json <<EOF
{
   "Version": "2012-10-17",
   "Statement": [
     {
       "Effect": "Allow",
       "Principal": {
         "Federated":
"arn:aws:iam::${AWS_ACCT}:oidc-provider/${OIDC_ISSUER}"
       },
       "Action": "sts:AssumeRoleWithWebIdentity",
       "Condition": {
         "StringLike": {
           "${OIDC_ISSUER}:sub":
"system:serviceaccount:kube-system:efs-csi-controller-sa*",
           "${OIDC_ISSUER}:aud": "sts.amazonaws.com" 
         }
       }
     }
   ]
}
EOF

aws iam update-assume-role-policy --role-name "$role_name" --policy-document file://./iam/efs-csi-trust-policy.json

echo "📦 Installing EFS CSI driver add-on..."
eksctl create addon \
  --cluster "$cluster_name" \
  --name aws-efs-csi-driver \
  --version latest \
  --service-account-role-arn arn:aws:iam::$AWS_ACCT:role/$role_name \
  --force

echo "💾 Creating EFS filesystem..."
sed -i "s/CLUSTER_NAME=.*/CLUSTER_NAME=\"$cluster_name\"/" eks/efs/create-efs.sh
./eks/efs/create-efs.sh

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
sed -i "s/fileSystemId: .*/fileSystemId: $EFS_ID/" eks/efs/efs-sc.yaml
kubectl create -f eks/efs/efs-sc.yaml

##ALB Ingress controller policy
# If you've created the policy previously
ALBIC_POLICY_ARN=$(aws iam list-policies \
  --query "Policies[?PolicyName=='AWSLoadBalancerControllerPolicy'].Arn" \
  --output text)

# If you haven't...
if [ -z $MY_POLICY_ARN ]; then
  ALBIC_POLICY_ARN=$(aws iam create-policy \
    --policy-name AWSLoadBalancerControllerPolicy \
    --policy-document file://./iam/alb-ingress-controller-policy.json | jq -r .Policy.Arn)
fi

eksctl create iamserviceaccount  \
  --cluster=$cluster_name  \
  --namespace=kube-system  \
  --name=aws-load-balancer-controller  \
  --role-name=AmazonEKSLoadBalancerControllerRole  \
  --attach-policy-arn=$ALBIC_POLICY_ARN  \
  --approve  \
  --region $AWS_DEFAULT_REGION

helm repo add eks https://aws.github.io/eks-charts
helm repo update eks

export K8S_VPC=$(eksctl get cluster $cluster_name -o json | jq -r '.[0].ResourcesVpcConfig.VpcId')

helm install aws-load-balancer-controller eks/aws-load-balancer-controller  \
  -n kube-system  \
  --set clusterName=$cluster_name  \
  --set serviceAccount.create=false  \
  --set serviceAccount.name=aws-load-balancer-controller  \
  --set region=$AWS_DEFAULT_REGION  \
  --set vpcId=$K8S_VPC

# Wait for deployment to complete...
kubectl rollout status deployment/aws-load-balancer-controller -n kube-system

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

sleep 10

#Create rabbitmq self-signed certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout tls.key -out tls.crt -subj "/CN=my-rabbit"
kubectl create secret generic my-rabbitmq-server-certificate \
   --from-file=ca.crt=certs/tls.crt \
   --from-file=tls.crt=certs/tls.crt \
   --from-file=tls.key=certs/tls.key \
   -n default

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

[[ "$?" == "0" ]] && echo "Cluster created successfully."

echo "RabbitMQ accessible at: $rabbitmqdns"
echo "RabbitMQ username: $rabbitusername"
echo "RabbitMQ password: $rabbitpassword"
