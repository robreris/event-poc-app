import pika
import json
import os

QUEUE_NAME = "ppt-uploaded"
host = os.environ.get("RABBITMQ_HOST", "rabbitmq")
username = os.environ.get("RABBIT_USERNAME", "")
password = os.environ.get("RABBIT_PASSWORD", "")
credentials = pika.PlainCredentials(username, password)
params = pika.ConnectionParameters(host=host, credentials=credentials)
print(f"RabbitMQ host: {host}")

def publish_message(data: dict):
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    message = json.dumps(data)
    channel.basic_publish(
        exchange='',
        routing_key=QUEUE_NAME,
        body=message,
        properties=pika.BasicProperties(delivery_mode=2)  # make message persistent
    )

    connection.close()
