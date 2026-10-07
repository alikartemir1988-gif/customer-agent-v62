FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    APP_SERVICE=core \
    TELEGRAM_REGISTER_WEBHOOK_ON_START=false \
    DEMO_COOKIE_SECURE=true

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser \
    && chown appuser:appuser /app

COPY --chown=appuser:appuser app.py dashboard.py demo_app.py support.py observability.py gunicorn.conf.py ./
COPY --chown=appuser:appuser templates/ ./templates/
COPY --chown=appuser:appuser scripts/start_service.py scripts/check_runtime_health.py ./scripts/

ARG APP_GIT_COMMIT=""
ENV APP_GIT_COMMIT=${APP_GIT_COMMIT}
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=12s --start-period=60s --retries=3 \
    CMD ["python", "scripts/check_runtime_health.py"]
ENTRYPOINT ["python", "scripts/start_service.py"]
