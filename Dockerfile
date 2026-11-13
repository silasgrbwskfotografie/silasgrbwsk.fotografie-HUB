FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/Berlin \
    STUDIO_HOST=0.0.0.0 \
    STUDIO_PORT=3000 \
    STUDIO_DATA=/data

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 1000 --home /app studio \
 && mkdir -p /data && chown studio /data

WORKDIR /app
COPY --chown=studio server.py ./
COPY --chown=studio static ./static

USER studio
VOLUME ["/data"]
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:3000/healthz', timeout=4).status == 200 else 1)"

CMD ["python", "server.py"]
