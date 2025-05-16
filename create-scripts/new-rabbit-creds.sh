#!/bin/bash

# Run this after creating a new RabbitMQ cluster if you need to copy its creds to a new namespace.

app_namespace=$1

rabbitusername=$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.username}" | base64 --decode)
rabbitpassword=$(kubectl get secret my-rabbit-default-user -o jsonpath="{.data.password}" | base64 --decode)

kubectl get secret my-rabbit-default-user -n $app_namespace &> /dev/null && \
   kubectl delete secret my-rabbit-default-user -n $app_namespace && \
     echo "Giving deletion five seconds to register..." && sleep 5

echo "Recreating secrets in $app_namespace namespace..."

kubectl create secret generic my-rabbit-default-user \
  --from-literal=username="$rabbitusername" \
  --from-literal=password="$rabbitpassword" \
  -n $app_namespace
