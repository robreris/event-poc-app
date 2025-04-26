#!/bin/bash
set -euo pipefail

AWS_DEFAULT_REGION=us-east-1
app_namespace=event-poc
cluster_name=$(eksctl get cluster -o json | jq -r ".[0].Name")

kubectl create -f eks/shared-artifacts-pvc.yaml

helm repo add external-secrets https://charts.external-secrets.io
helm repo update

helm install external-secrets external-secrets/external-secrets \
  --namespace $app_namespace \
  --create-namespace

echo "Sleeping 30 seconds for ESO helm installation to come up..."

# If you've created the policy previously
MY_POLICY_ARN=$(aws iam list-policies \
  --query "Policies[?PolicyName=='ESOSecretsManagerReadAccess'].Arn" \
  --output text)

# If you haven't...
if [ -z $MY_POLICY_ARN ]; then
  MY_POLICY_ARN=$(aws iam create-policy \
    --policy-name ESOSecretsManagerReadAccess \
    --policy-document file://./iam/eso-secrets-policy.json | jq -r .Policy.Arn)
fi

eksctl create iamserviceaccount \
  --name eso-sa \
  --namespace $app_namespace \
  --cluster $cluster_name \
  --attach-policy-arn $MY_POLICY_ARN  \
  --approve \
  --role-name ESOSecretsAccessRole

echo "Ready to build and push docker images.\n"
echo "Run 'kubectl create -f /manifests' to start deployments."
