#!/bin/bash

set -e

NAMESPACE="event-poc"

echo "Creating namespace..."
kubectl create namespace $NAMESPACE || echo "Namespace $NAMESPACE already exists"

echo "Applying PVC..."
kubectl apply -f k8s/pvc.yaml

echo "Deploying TTS service..."
kubectl apply -f k8s/deployments/tts.yaml

echo "Deploying Renderer service..."
kubectl apply -f k8s/deployments/renderer.yaml

echo "Deploying Coordinator service..."
kubectl apply -f k8s/deployments/coordinator.yaml

echo "Waiting 10 seconds to let RabbitMQ queues get initialized..."
sleep 10

echo "Kicking off Producer Job..."
kubectl apply -f k8s/deployments/producer-job.yaml

echo
echo "All components deployed!"
echo "You can watch logs using:"
echo "  kubectl logs -n $NAMESPACE deployment/tts -f"
echo "  kubectl logs -n $NAMESPACE deployment/renderer -f"
echo "  kubectl logs -n $NAMESPACE deployment/coordinator -f"
