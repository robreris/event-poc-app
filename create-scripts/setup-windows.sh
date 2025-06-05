#!/bin/bash
set -e

CLUSTER_NAME="event-driven-poc"
CLUSTER_ID="cluster-$(date +%s)"
REGION="us-east-1"
RABBITMQ_ENDPOINT="rabbitmq.default.svc.cluster.local"
EFS_MOUNT_TARGET="fs-abc123.efs.${REGION}.amazonaws.com"
AMI_ID="ami-00c644911fc9f5f18"

# Get EKS cluster infra info
CLUSTER_INFO=$(eksctl get cluster --name "$CLUSTER_NAME" --region "$REGION" -o json)
VPC_ID=$(echo "$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.VpcId')
SUBNET_IDS=$(echo "$CLUSTER_INFO" | jq -r '.[0].ResourcesVpcConfig.SubnetIds[]' | head -n 2)
SUBNET_ID_1=$(echo "$SUBNET_IDS" | sed -n '1p')
SUBNET_ID_2=$(echo "$SUBNET_IDS" | sed -n '2p')
SG_ID=$(aws ec2 describe-instances --filters "Name=tag:eks:cluster-name,Values=$CLUSTER_NAME" --query 'Reservations[*].Instances[*].SecurityGroups[*].GroupId' --output text | uniq)
if [[ -z "$VPC_ID" || -z "$SUBNET_ID_1" || -z "$SUBNET_ID_2" || -z "$SG_ID" ]]; then
  echo "❌  Failed to retrieve all required values. Aborting."
  exit 1
fi

echo "✅  VPC ID: $VPC_ID"
echo "✅  Subnet 1: $SUBNET_ID_1"
echo "✅  Subnet 2: $SUBNET_ID_2"
echo "✅  Security Group ID: $SG_ID"

# 1. Store parameters in SSM
aws ssm put-parameter --name "/myapp/rabbitmq" --value "$RABBITMQ_ENDPOINT" --type String --overwrite --region "$REGION"
aws ssm put-parameter --name "/myapp/nfs" --value "$EFS_MOUNT_TARGET" --type String --overwrite --region "$REGION"

# 2. Deploy launch template (pass in parameters or use stack defaults)
aws cloudformation deploy \
  --template-file /eks/v2/windows-ppt/windows-ppt-cft.yaml \
  --stack-name render-agent-launch-template \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    AmiId=$AMI_ID \
    IamInstanceProfile=MyRenderAgentProfile \
    KeyName=my-keypair \
    SubnetId=subnet-xxxxxxxx \
    SecurityGroupId=sg-xxxxxxxx
