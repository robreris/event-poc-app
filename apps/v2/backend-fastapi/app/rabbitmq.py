import os
import json
import pika
import time
from typing import Dict, Any
from .config import get_rabbitmq_credentials, RABBITMQ_HOST, RABBITMQ_PORT

class RabbitMQConnection:
    _instance = None
    _connection = None
    _channel = None
    _is_consuming = False

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_connection(self, max_retries=5, retry_delay=5):
        """
        Create and return a RabbitMQ connection with retry logic
        
        Args:
            max_retries: Maximum number of connection attempts
            retry_delay: Delay between retries in seconds
        """
        if self._connection and self._connection.is_open:
            return self._connection

        for attempt in range(max_retries):
            try:
                credentials = get_rabbitmq_credentials()
                connection_params = pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    port=RABBITMQ_PORT,
                    credentials=pika.PlainCredentials(
                        credentials["username"],
                        credentials["password"]
                    ),
                    heartbeat=600,
                    blocked_connection_timeout=300,
                    connection_attempts=3,
                    retry_delay=5
                )
                self._connection = pika.BlockingConnection(connection_params)
                return self._connection
            except pika.exceptions.AMQPConnectionError as e:
                if attempt < max_retries - 1:
                    print(f"Failed to connect to RabbitMQ (attempt {attempt + 1}/{max_retries}). Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    print(f"Failed to connect to RabbitMQ after {max_retries} attempts")
                    raise

    def get_channel(self):
        """Get or create a channel"""
        if self._channel and self._channel.is_open:
            return self._channel

        connection = self.get_connection()
        self._channel = connection.channel()
        return self._channel

    def close(self):
        """Close the connection and channel"""
        self._is_consuming = False
        if self._channel and self._channel.is_open:
            self._channel.close()
        if self._connection and self._connection.is_open:
            self._connection.close()
        self._channel = None
        self._connection = None

def publish_message(message: Dict[str, Any], queue: str = "file_processing"):
    """
    Publish a message to RabbitMQ
    
    Args:
        message: The message to publish
        queue: The queue to publish to
    """
    rabbitmq = RabbitMQConnection.get_instance()
    try:
        channel = rabbitmq.get_channel()
        
        # Declare the queue
        channel.queue_declare(queue=queue, durable=True)
        
        # Publish the message
        channel.basic_publish(
            exchange='',
            routing_key=queue,
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,  # make message persistent
            )
        )
    except Exception as e:
        print(f"Error publishing message: {str(e)}")
        rabbitmq.close()  # Close connection on error
        raise

def rabbitmq_listener(queue: str = "file_processing", callback=None):
    """
    Start a RabbitMQ listener
    
    Args:
        queue: The queue to listen to
        callback: The callback function to process messages
    """
    rabbitmq = RabbitMQConnection.get_instance()
    last_reconnect = 0
    reconnect_delay = 5

    while True:
        try:
            if rabbitmq._is_consuming:
                time.sleep(1)
                continue

            if time.time() - last_reconnect < reconnect_delay:
                time.sleep(1)
                continue

            channel = rabbitmq.get_channel()
            
            # Declare the queue
            channel.queue_declare(queue=queue, durable=True)
            
            # Set up the callback
            if callback:
                channel.basic_consume(
                    queue=queue,
                    on_message_callback=callback,
                    auto_ack=True
                )
            
            print(f"Started consuming from queue: {queue}")
            rabbitmq._is_consuming = True
            
            # Start consuming
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError:
            print("Lost connection to RabbitMQ. Reconnecting...")
            rabbitmq.close()
            last_reconnect = time.time()
        except Exception as e:
            print(f"Error in RabbitMQ listener: {str(e)}")
            rabbitmq.close()
            last_reconnect = time.time() 
