FROM python:3.9-slim

# Install RabbitMQ client
RUN pip install pika

# Copy in the application logic
COPY app.py /app.py

# Set working directory and run app
WORKDIR /
CMD ["python", "/app.py"]
