#!/bin/bash

AWS_DEFAULT_REGION=us-east-1
app_namespace=event-poc
cluster_name=event-driven-poc
#cluster_name=$(eksctl get cluster -o json | jq -r ".[0].Name")

kubectl delete -f manifests/

kubectl delete -f rabbitmq/rabbitmq-cluster.yaml

aws cloudformation delete-stack --stack-name $cluster_name-efs

eksctl delete iamserviceaccount --name efs-csi-controller-sa-$cluster_name --cluster $cluster_name

eksctl delete addon --cluster $cluster_name --name aws-efs-csi-driver

aws cloudformation delete-stack --stack-name eksctl-$cluster_name-addon-iamserviceaccount-event-poc-eso-sa
aws cloudformation delete-stack --stack-name eksctl-$cluster_name-addon-iamserviceaccount-kube-system-efs-csi-controller-sa-$cluster_name
aws cloudformation delete-stack --stack-name eksctl-$cluster_name-addon-iamserviceaccount-kube-system-aws-load-balancer-controller


eksctl delete cluster $cluster_name
