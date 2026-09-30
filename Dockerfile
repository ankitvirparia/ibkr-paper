FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY tests/ ./tests/
COPY config.yaml .

EXPOSE 8003
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8003"]
