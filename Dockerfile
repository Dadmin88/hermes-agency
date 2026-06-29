# syntax=docker/dockerfile:1

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HERMES_HOME=/data/hermes \
    HERMES_AGENCY_MODE=all \
    HERMES_AGENCY_INSTALL_STAFF=1 \
    HERMES_AGENCY_START_NODE=1 \
    HERMES_AGENCY_MODEL_SET=openai-codex-only

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY hermes-agency ./hermes-agency
COPY scripts ./scripts
COPY docker ./docker

RUN python -m pip install --upgrade pip \
    && python -m pip install -e .

VOLUME ["/data/hermes"]
ENTRYPOINT ["tini", "--", "python", "docker/run-agency.py"]
CMD ["all"]
