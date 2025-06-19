import os
# S3 config first so it can be imported without kubernetes dependency
S3_BUCKET = os.getenv("S3_BUCKET", "your-s3-bucket-name")
S3_REGION = os.getenv("S3_REGION", "us-east-1")

# Get configuration from environment variables
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = os.getenv("RABBITMQ_PORT", "5672")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")

def get_rabbitmq_credentials():
    """
    Get RabbitMQ credentials either from Kubernetes secrets or environment variables
    """
    try:
        # Try to load Kubernetes config
        try:
            import kubernetes  # type: ignore
            from kubernetes import client, config  # type: ignore
            config.load_incluster_config()
            # If we're in Kubernetes, get credentials from secret
            v1 = client.CoreV1Api()
            secret = v1.read_namespaced_secret("my-rabbit-default-user", "event-poc")
            return {
                "username": secret.data["username"].decode(),
                "password": secret.data["password"].decode()
            }
        except (Exception,):
            # If we're not in Kubernetes or secret doesn't exist, use environment variables
            return {
                "username": RABBITMQ_USER,
                "password": RABBITMQ_PASSWORD
            }
    except Exception as e:
        print(f"Error getting RabbitMQ credentials: {str(e)}")
        # Fallback to environment variables
        return {
            "username": RABBITMQ_USER,
            "password": RABBITMQ_PASSWORD
        } 
