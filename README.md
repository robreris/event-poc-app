## Video-As-Code POC/MVP Set-Up in EKS

### Create EKS cluster, RabbitMQ deployment, and VAC resources

First, update info for your environment and as desired in **create-scripts/create-cluster.sh**:

```
...
AWS_ACCT="12345678"  # Enter your account number here
cluster_name="event-driven-poc"
app_namespace="event-poc"
export AWS_DEFAULT_REGION=us-east-1
...
```

Do the same in **create-scripts/create-event-poc.sh**:
```
...
export AWS_DEFAULT_REGION=us-east-1

app_namespace=event-poc
...
```

Then go ahead and deploy:

```bash
./create-scripts/create-cluster.sh

./create-scripts/create-event-poc.sh

kubectl create -f manifests/
```

Website will be at:
```bash
kubectl get svc ppt-upload-service -n event-poc -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

#### Logging and troubleshooting:

```bash
# Check logs
kubectl logs -l app=ppt-upload -n event-poc
kubectl logs -l app=ppt-extractor -n event-poc
kubectl logs -l app=tts-processor -n event-poc
kubectl logs -l app=video-producer -n event-poc
```

SSH into Pod containers for troubleshooting:
```bash
kubectl exec -it $(kubectl get pod -l app=ppt-upload -n event-poc -o jsonpath="{.items[0].metadata.name}") -n event-poc -- sh
kubectl exec -it $(kubectl get pod -l app=ppt-extractor -n event-poc -o jsonpath="{.items[0].metadata.name}") -n event-poc -- sh
kubectl exec -it $(kubectl get pod -l app=tts-processor -n event-poc -o jsonpath="{.items[0].metadata.name}") -n event-poc -- sh
kubectl exec -it $(kubectl get pod -l app=video-producer -n event-poc -o jsonpath="{.items[0].metadata.name}") -n event-poc -- sh

# After SSH'ing in:

> ls /artifacts
#notes  slides  tts_output  video-output

```

#### Cluster Teardown

First, as with the create scripts, update the region and namespace in **create-scripts/delete-cluster-and-poc.sh**:

```bash
AWS_DEFAULT_REGION=us-east-1
app_namespace=event-poc
```

Then run the script to tear down:

```bash
./create-scripts/delete-cluster-and-poc.sh
```
