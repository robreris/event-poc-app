#!/bin/bash

AWS_DEFAULT_REGION=us-east-1
app_namespace=event-poc
cluster_name=event-driven-poc
#cluster_name=$(eksctl get cluster -o json | jq -r ".[0].Name")

VERS=$1

if [ $# -eq 0 ] || [ $# -gt 1 ]; then
  echo "Zero or too many arguments supplied..."
  echo "Example: ./create-scripts/delete-cluster-and-poc.sh v1"
  exit 1
fi

kubectl delete -f manifests/${VERS}

kubectl delete -f rabbitmq/${VERS}/rabbitmq-cluster.yaml

aws cloudformation delete-stack --stack-name $cluster_name-efs

aws cloudformation delete-stack --stack-name eks-addon-roles

eksctl delete cluster $cluster_name
