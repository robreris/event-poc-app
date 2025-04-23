## Setting up ESO

Run 'aws configure sso' and set environment variables:

```bash
export AWS_DEFAULT_REGION=us-east-1
export cluster_name=event-driven-poc
export namespace=event-poc
```

Install ESO:
```bash
helm repo add external-secrets https://charts.external-secrets.io
helm repo update

helm install external-secrets external-secrets/external-secrets \
  --namespace event-poc \
  --create-namespace
```

```bash
# If you've created the policy previously
MY_POLICY_ARN=$(aws iam list-policies \
  --query "Policies[?PolicyName=='ESOSecretsManagerReadAccess'].Arn" \
  --output text)

# If you haven't...
if [ -z $MY_POLICY_ARN ]; then
  MY_POLICY_ARN=$(aws iam create-policy \
    --policy-name ESOSecretsManagerReadAccess \
    --policy-document file://eso-secrets-policy.json | jq -r .Policy.Arn)
fi
```

```bash
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
