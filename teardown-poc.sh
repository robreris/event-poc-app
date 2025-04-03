#!/bin/bash

NAMESPACE="event-poc"

echo "Deleting all POC workloads and PVCs..."

kubectl delete job producer -n $NAMESPACE --ignore-not-found
kubectl delete deployment tts renderer coordinator -n $NAMESPACE --ignore-not-found
kubectl delete pvc shared-artifacts -n $NAMESPACE --ignore-not-found
kubectl delete pv efs-pv --ignore-not-found
kubectl delete namespace $NAMESPACE --ignore-not-found

echo "If you deployed RabbitMQ via Helm, run:"
echo "  helm uninstall rabbitmq"
echo
echo "If you created an EFS stack via CloudFormation, delete with:"
echo "  aws cloudformation delete-stack --stack-name event-poc-efs"

echo "Teardown complete."
