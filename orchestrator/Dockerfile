FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg mkvtoolnix \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src /app/src
COPY alembic.ini /app/alembic.ini
COPY alembic/ /app/alembic/

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "orchestrator.app:app", "--host", "0.0.0.0", "--port", "8000"]
