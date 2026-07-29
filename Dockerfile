FROM python:3.14-slim AS runtime
ARG APP_VERSION=0.2.0
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_VERSION=${APP_VERSION} \
    PORT=8000
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tini \
 && update-ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
 && python -m pip install -r requirements.txt
COPY app ./app
COPY scripts/start.sh ./scripts/start.sh
RUN chmod +x ./scripts/start.sh \
 && mkdir -p /data/mirror/nvd /certs
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/scripts/start.sh"]

FROM runtime AS test
COPY requirements-dev.txt ./requirements-dev.txt
RUN python -m pip install -r requirements-dev.txt
COPY tests ./tests
COPY pytest.ini pyproject.toml ./
CMD ["pytest", "-q"]
