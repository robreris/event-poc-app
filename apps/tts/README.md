## Setting up ESO

Install ESO:
```bash
helm repo add external-secrets https://charts.external-secrets.io
helm repo update

helm install external-secrets external-secrets/external-secrets \
  --namespace event-poc \
  --create-namespace
```

```bash
MY_POLICY_ARN=$(aws iam create-policy \
  --policy-name ESOSecretsManagerReadAccess \
  --policy-document file://eso-secrets-policy.json | jq -r .Policy.Arn)

```

```bash
cluster_name=event-driven-poc
namespace=event-poc

eksctl create iamserviceaccount \
  --name eso-sa \
  --namespace event-poc \
  --cluster $cluster_name \
  --attach-policy-arn $MY_POLICY_ARN  \
  --approve \
  --role-name ESOSecretsAccessRole
```

```bash
kubectl create -f manifests/external-secret.yaml
kubectl create -f manifests/secret-store.yaml
```
