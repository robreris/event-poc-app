### Basic RabbitMQ Cluster Set-Up

Create cluster
```bash
eksctl create cluster -f eks/event-poc-cluster.yaml
```

Set up EFS
```bash
./eks/get-cft-params.sh
```

Set up EFS CSI driver
```bash
kubectl apply -k "github.com/kubernetes-sigs/aws-efs-csi-driver/deploy/kubernetes/overlays/stable/ecr/?ref=release-1.5"
```

**Ensure NFS mount security groups allow NFS (port 2049) access from the security group attached to cluster EC2 instances**

Update the EFS storage class object spec with new file system id and deploy
```bash
kubectl create -f infra/efs-sc.yaml
```

Deploy PVC
```bash
kubectl create -f k8s/pvc.yaml
```

Set up RabbitMQ K8S Operator
```bash
kubectl create namespace rabbitmq-system
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update
helm install rabbitmq-operator bitnami/rabbitmq-cluster-operator --namespace rabbitmq-system
```

Deploy RabbitMQ cluster
```bash
kubectl apply -f rabbitmq/rabbitmq-cluster.yaml
kubectl get secret my-rabbit-default-user -o jsonpath="{.data.username}" | base64 --decode; echo
kubectl get secret my-rabbit-default-user -o jsonpath="{.data.password}" | base64 --decode; echo
```

Optionally create a ConfigMap with RabbitMQ env vars for login/host/etc
```bash
kubectl create -f rabbitmq-config.yaml
```
