FROM python:3.11-slim

ARG KIRITO_IMAGE_TAG=2026-05-26-early4
LABEL org.opencontainers.image.title="KIRITO early4" \
      org.opencontainers.image.description="Docker: BTC 5m early-entry 4-strike opposite strategy" \
      org.opencontainers.image.version="${KIRITO_IMAGE_TAG}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    KIRITO_STATE_PATH=/app/data/kirito_state.json

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin appuser

COPY requirements.txt /app/requirements.txt

RUN pip install --upgrade pip && \
    pip install -r /app/requirements.txt

COPY main.py /app/main.py
COPY kirito_engine.py /app/kirito_engine.py
COPY check_wallet.py /app/check_wallet.py
COPY config.py /app/config.py
COPY trader.py /app/trader.py
COPY market_locator.py /app/market_locator.py
COPY http_session.py /app/http_session.py
COPY clob_fak.py /app/clob_fak.py
COPY polymarket_ws.py /app/polymarket_ws.py
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN chmod +x /docker-entrypoint.sh \
    && mkdir -p /app/logs /app/exports /app/data \
    && chown -R appuser:appuser /app

# Entrypoint starts as root to chown bind mounts, then drops to appuser via gosu.
USER root
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "main.py"]
