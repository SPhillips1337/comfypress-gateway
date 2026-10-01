FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    KEY_DB_PATH=/data/keys.sqlite3 \
    GATEWAY_PORT=8190

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY comfy_gateway ./comfy_gateway
RUN mkdir -p /data && chown -R 10001:10001 /app /data

USER 10001:10001
VOLUME ["/data"]
EXPOSE 8190
ENTRYPOINT ["python", "-m", "comfy_gateway"]
CMD ["serve"]
