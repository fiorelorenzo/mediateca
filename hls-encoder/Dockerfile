FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        watchdog==5.0.3 \
        requests==2.32.3

WORKDIR /app
COPY encoder.py /app/encoder.py

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-u", "/app/encoder.py"]
