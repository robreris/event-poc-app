#!/bin/bash

AWS_DEFAULT_REGION=us-east-1
app_namespace=event-poc
cluster_name=event-driven-poc
#cluster_name=$(eksctl get cluster -o json | jq -r ".[0].Name")

kubectl delete -f manifests/

kubectl delete -f rabbitmq/rabbitmq-cluster.yaml

aws cloudformation delete-stack --stack-name $cluster_name-efs

aws cloudformation delete-stack --stack-name eks-addon-roles

eksctl delete cluster $cluster_name
