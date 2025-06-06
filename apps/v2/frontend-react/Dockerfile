FROM python:3.10-slim

WORKDIR /app
COPY . .
COPY static ./static
RUN pip install --no-cache-dir -r requirements.txt

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
