### Basic RabbitMQ Cluster Set-Up

Create cluster
```bash
export AWS_DEFAULT_REGION=us-east-1
eksctl create cluster -f eks/event-poc-cluster.yaml
cluster_name=$(eksctl get cluster --output json | jq -r .[].Name)
```

Set up the EFS CSI Driver Add-on
```bash
role_name=AmazonEKS_EFS_CSI_DriverRole

eksctl utils associate-iam-oidc-provider \
  --cluster $cluster_name \
  --approve

eksctl create iamserviceaccount  \
  --name efs-csi-controller-sa   \
  --namespace kube-system   \
  --cluster $cluster_name  \
  --role-name $role_name  \
  --role-only   \
  --attach-policy-arn arn:aws:iam::aws:policy/service-role/AmazonEFSCSIDriverPolicy  \
  --approve

TRUST_POLICY=$(aws iam get-role --output json --role-name $role_name --query 'Role.AssumeRolePolicyDocument' | \
    sed -e 's/efs-csi-controller-sa/efs-csi-*/' -e 's/StringEquals/StringLike/')

aws iam update-assume-role-policy --role-name $role_name --policy-document "$TRUST_POLICY"

AWS_ACCT=<your AWS Account number>
eksctl create addon --cluster event-driven-poc --name aws-efs-csi-driver --version latest --service-account-role-arn arn:aws:iam::$AWS_ACCT:role/AmazonEKS_EFS_CSI_DriverRole --force
```

Set up EFS
```bash
./infra/create-efs.sh
```
**Ensure EFS mount security groups have been configured to allow NFS (port 2049) access from the security group attached to cluster EC2 instances**

Update the EFS storage class object spec with new file system id and deploy
```bash
EFS_ID=$(aws efs describe-file-systems \
  --query "FileSystems[?Tags[?Key=='Name' && Value=='eks-event-poc-efs']].FileSystemId" \
  --output text)

sed -i "s/fileSystemId: .*/fileSystemId: $EFS_ID/" infra/efs-sc.yaml

kubectl create -f infra/efs-sc.yaml
```

Update PVC object spec to reference new filesystem id and deploy
```bash
EFS_ID=$(aws efs describe-file-systems \
  --query "FileSystems[?Tags[?Key=='Name' && Value=='eks-event-poc-efs']].FileSystemId" \
  --output text)
sed -i "s/volumeHandle: .*/volumeHandle: $EFS_ID/" k8s/pvc.yaml

kubectl create namespace event-poc
kubectl create -f k8s/pvc.yaml
```

Set up RabbitMQ K8S Operator
```bash
kubectl create namespace rabbitmq-system
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update
helm install rabbitmq-operator bitnami/rabbitmq-cluster-operator --namespace rabbitmq-system
```

Deploy RabbitMQ cluster and get creds for console access
```bash
kubectl apply -f rabbitmq/rabbitmq-cluster.yaml

# Get console DNS
rabbitmqdns="http://$(kubectl get svc my-rabbit -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'):15672"
echo $rabbitmqdns    # paste into browser

# Get credentials for log in
rabbitusername=$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.username}" | base64 --decode; echo)
rabbitpassword=$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.password}" | base64 --decode; echo)

# Copy secrets to event-poc namespace
kubectl create secret generic my-rabbit-default-user \
  --from-literal=username=$rabbitusername \
  --from-literal=password=$rabbitpassword \
  -n event-poc
```

Build the image and push to ECR, then deploy.
```bash
kubectl create ./k8s/deployments/

# Check logs
kubectl logs -l app=coordinator -n event-poc
kubectl logs -l app=tts -n event-poc
kubectl logs -l app=renderer -n event-poc
kubectl logs -l job-name=producer -n event-poc
```

SSH into Pod containers for troubleshooting:
```bash
kubectl exec -it $(kubectl get pod -l app=coordinator -n event-poc -o jsonpath="{.items[0].metadata.name}") -n event-poc -- sh
kubectl exec -it $(kubectl get pod -l app=renderer -n event-poc -o jsonpath="{.items[0].metadata.name}") -n event-poc -- sh
kubectl exec -it $(kubectl get pod -l app=tts -n event-poc -o jsonpath="{.items[0].metadata.name}") -n event-poc -- sh
kubectl exec -it $(kubectl get pod -l job-name=producer -n event-poc -o jsonpath="{.items[0].metadata.name}") -n event-poc -- sh
```

Cluster teardown:
```bash
kubectl delete -f k8s/deployments

kubectl delete -f rabbitmq/rabbitmq-cluster.yaml

aws cloudformation delete-stack --stack-name event-driven-poc-efs

eksctl delete iamserviceaccount --name efs-csi-controller-sa --cluster event-driven-poc

eksctl delete addon --cluster event-driven-poc --name aws-efs-csi-driver

eksctl delete cluster event-driven-poc
```
