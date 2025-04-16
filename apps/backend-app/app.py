import os
import sys
import time
import json
import pika
import socket

ROLE = os.getenv("ROLE", "")
print(f"######Role is: {ROLE}")

def ensure_path(job_id, role):
    path = f"/artifacts/{job_id}/{role}"
    os.makedirs(path, exist_ok=True)
    with open(f"{path}/output.txt", "w") as f:
        f.write(f"{role} completed at {time.time()}")

host = os.environ.get("RABBIT_HOST", "rabbitmq")
username = os.environ.get("RABBIT_USERNAME", "")
password = os.environ.get("RABBIT_PASSWORD", "")
credentials = pika.PlainCredentials(username, password)
params = pika.ConnectionParameters(host=host, credentials=credentials)
conn = pika.BlockingConnection(params)
channel = conn.channel()

channel.queue_declare(queue='ppt-uploaded', durable=True)
channel.queue_declare(queue='tts-complete', durable=True)
channel.queue_declare(queue='rendering-complete', durable=True)
channel.queue_declare(queue='start-assembly', durable=True)

if ROLE == "tts":
    channel.exchange_declare(exchange='ppt-uploaded-ex', exchange_type='fanout', durable=True)
    channel.queue_declare(queue='ppt-uploaded-tts', durable=True)
    channel.queue_bind(exchange='ppt-uploaded-ex', queue='ppt-uploaded-tts')

    def callback(ch, method, properties, body):
        msg = json.loads(body)
        print("TTS: Received", msg)
        time.sleep(2)
        done = { "event": "tts-complete", "job_id": msg["job_id"] }
        channel.basic_publish(exchange='', routing_key='tts-complete', body=json.dumps(done), properties=pika.BasicProperties(delivery_mode=2))
        ensure_path(msg["job_id"], "tts")
        print("TTS: Sent tts-complete")
  
    channel.basic_consume(queue='ppt-uploaded-tts', on_message_callback=callback, auto_ack=True)
    print("Renderer: starting to consume ppt-uploaded...")
    channel.start_consuming()

elif ROLE == "renderer":
    channel.exchange_declare(exchange='ppt-uploaded-ex', exchange_type='fanout', durable=True)
    channel.queue_declare(queue='ppt-uploaded-renderer', durable=True)
    channel.queue_bind(exchange='ppt-uploaded-ex', queue='ppt-uploaded-renderer')

    def callback(ch, method, properties, body):
        msg = json.loads(body)
        print("Renderer: Received", msg)
        time.sleep(3)
        done = { "event": "rendering-complete", "job_id": msg["job_id"] }
        channel.basic_publish(exchange='', routing_key='rendering-complete', body=json.dumps(done), properties=pika.BasicProperties(delivery_mode=2))
        ensure_path(msg["job_id"], "renderer")
        print("Renderer: Sent rendering-complete")

    channel.basic_consume(queue='ppt-uploaded-renderer', on_message_callback=callback, auto_ack=True)
    print("Renderer: starting to consume ppt-uploaded...")
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
            channel.basic_publish(exchange='', routing_key='start-assembly', body=json.dumps(msg), properties=pika.BasicProperties(delivery_mode=2))

    def tts_callback(ch, method, props, body):
        msg = json.loads(body)
        print("Coordinator: Got", msg["event"])
        handle_complete("tts-complete", msg["job_id"])

    def renderer_callback(ch, method, props, body):
        msg = json.loads(body)
        print("Coordinator: Got", msg["event"])
        handle_complete("rendering-complete", msg["job_id"])

    print("Coordinator: starting to consume tts-complete and rendering-complete...")
    channel.basic_consume(queue='tts-complete', on_message_callback=tts_callback, auto_ack=True)
    channel.basic_consume(queue='rendering-complete', on_message_callback=renderer_callback, auto_ack=True)
    channel.start_consuming()

elif ROLE == "assembler":
    def callback(ch, method, props, body):
        msg = json.loads(body)
        print("Assembler: Received", msg)
        ensure_path(msg["job_id"], "assembler")
        print("Assembler: Final assembly complete")

    print("Assembler: starting to consume start-assembly...")
    channel.basic_consume(queue='start-assembly', on_message_callback=callback, auto_ack=True)
    channel.start_consuming()       
