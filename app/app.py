import os
import sys
import time
import json
import pika
import socket

JOB_ID = "job-123"
ROLE = os.getenv("ROLE", "producer")
print(f"######Role is: {ROLE}")

def ensure_path(job_id, role):
    path = f"/artifacts/{job_id}/{role}"
    os.makedirs(path, exist_ok=True)
    with open(f"{path}/output.txt", "w") as f:
        f.write(f"{role} completed at {time.time()}")

host = os.environ.get("RABBIT_HOST", "rabbitmq")
credentials = pika.PlainCredentials("user", "bitnami")
params = pika.ConnectionParameters(host=host, credentials=credentials)
for attempt in range(10):
    try:
        conn = pika.BlockingConnection(params)
        channel = conn.channel()
        break
    except pika.exceptions.AMQPConnectionError:
        print(f"{attempt+1}/10] Waiting for RabbitMQ to be ready...")
        time.sleep(3)
else:
    raise Exception("Failed to connect to RabbitMQ after 10 tries")

channel.queue_declare(queue='ppt-uploaded')
channel.queue_declare(queue='tts-complete')
channel.queue_declare(queue='rendering-complete')
channel.queue_declare(queue='start-assembly')

if ROLE == "producer":
    print("Producer waiting for consumers to be ready...")
    time.sleep(10)
    msg = { "event": "ppt-uploaded", "job_id": JOB_ID }
    channel.basic_publish(exchange='', routing_key='ppt-uploaded', body=json.dumps(msg))
    print("Producer: Sent ppt-uploaded")
    time.sleep(5)

elif ROLE == "tts":
    def callback(ch, method, properties, body):
        msg = json.loads(body)
        print("TTS: Received", msg)
        time.sleep(2)
        done = { "event": "tts-complete", "job_id": msg["job_id"] }
        channel.basic_publish(exchange='', routing_key='tts-complete', body=json.dumps(done))
        ensure_path(msg["job_id"], "tts")
        print("TTS: Sent tts-complete")

    channel.basic_consume(queue='ppt-uploaded', on_message_callback=callback, auto_ack=True)
    channel.start_consuming()

elif ROLE == "renderer":
    def callback(ch, method, properties, body):
        msg = json.loads(body)
        print("Renderer: Received", msg)
        time.sleep(3)
        done = { "event": "rendering-complete", "job_id": msg["job_id"] }
        channel.basic_publish(exchange='', routing_key='rendering-complete', body=json.dumps(done))
        ensure_path(msg["job_id"], "renderer")
        print("Renderer: Sent rendering-complete")

    channel.basic_consume(queue='ppt-uploaded', on_message_callback=callback, auto_ack=True)
    channel.start_consuming()

elif ROLE == "coordinator":
    states = {}

    def handle_complete(event_type, job_id):
        if job_id not in states:
            states[job_id] = {"tts": False, "render": False}
        if event_type == "tts-complete":
            states[job_id]["tts"] = True
        if event_type == "rendering-complete":
            states[job_id]["render"] = True
        if all(states[job_id].values()):
            print(f"Coordinator: All done for {job_id}, triggering final assembly.")
            msg = { "event": "start-assembly", "job_id": job_id }
            channel.basic_publish(exchange='', routing_key='start-assembly', body=json.dumps(msg))

    def tts_callback(ch, method, props, body):
        msg = json.loads(body)
        print("Coordinator: Got", msg["event"])
        handle_complete("tts-complete", msg["job_id"])

    def renderer_callback(ch, method, props, body):
        msg = json.loads(body)
        print("Coordinator: Got", msg["event"])
        handle_complete("rendering-complete", msg["job_id"])

    channel.basic_consume(queue='tts-complete', on_message_callback=tts_callback, auto_ack=True)
    channel.basic_consume(queue='rendering-complete', on_message_callback=renderer_callback, auto_ack=True)
    channel.start_consuming()

