FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY static/ ./static/
COPY tests/ ./tests/
COPY config.yaml .

EXPOSE 8005
# TLS on the Tailscale IP only (never 0.0.0.0: the box has a public IP).
CMD ["uvicorn", "src.api:app", "--host", "100.101.82.11", "--port", "8005", "--ssl-keyfile", "/certs/key.pem", "--ssl-certfile", "/certs/cert.pem"]
