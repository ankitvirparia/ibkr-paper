FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir playwright==1.49.0 \
    && playwright install --with-deps chromium
WORKDIR /app
COPY login.py /app/login.py
CMD ["python", "/app/login.py"]
RUN apt-get update && apt-get install -y --no-install-recommends xauth && rm -rf /var/lib/apt/lists/*
