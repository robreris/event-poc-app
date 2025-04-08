#!/bin/bash

CLUSTER_NAME="event-driven-poc"
REGION="us-east-1"
PARAM_FILE="params.json"

echo "Fetching EKS cluster details for: $CLUSTER_NAME"

CLUSTER_INFO=$(eksctl get cluster --name "$CLUSTER_NAME" --region "$REGION" -o json)

VPC_ID=$(echo "$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.VpcId')
SUBNET_IDS=$(echo "$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.SubnetIds[]' | head -n 2)
SUBNET_ID_1=$(echo "$SUBNET_IDS" | sed -n '1p')
SUBNET_ID_2=$(echo "$SUBNET_IDS" | sed -n '2p')
SG_ID=$(echo "$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.SecurityGroupIds[0]')

if [[ -z "$VPC_ID" || -z "$SUBNET_ID_1" || -z "$SUBNET_ID_2" || -z "$SG_ID" ]]; then
  echo "❌ Failed to retrieve all required values. Aborting."
  exit 1
fi

echo "✅ VPC ID: $VPC_ID"
echo "✅ Subnet 1: $SUBNET_ID_1"
echo "✅ Subnet 2: $SUBNET_ID_2"
echo "✅ Security Group ID: $SG_ID"

# Generate the CloudFormation parameter file
cat > "$PARAM_FILE" <<EOF
[
  {
    "ParameterKey": "VpcId",
    "ParameterValue": "$VPC_ID"
  },
  {
    "ParameterKey": "SubnetIdAz1",
    "ParameterValue": "$SUBNET_ID_1"
  },
  {
    "ParameterKey": "SubnetIdAz2",
    "ParameterValue": "$SUBNET_ID_2"
  },
  {
    "ParameterKey": "NodeSecurityGroup",
    "ParameterValue": "$SG_ID"
  }
]
EOF

echo "📄 CloudFormation parameters written to $PARAM_FILE"
echo "Deploying template..."

aws cloudformation create-stack \
  --stack-name event-driven-poc-efs \
  --template-body file://./efs.yaml \
  --parameters file://./$PARAM_FILE \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
