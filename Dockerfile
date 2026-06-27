# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS dashboard-web
WORKDIR /app/web/agency-dashboard
COPY web/agency-dashboard/package*.json ./
RUN npm ci
COPY web/agency-dashboard ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HERMES_HOME=/data/hermes \
    HERMES_DASHBOARD_HOST=0.0.0.0 \
    HERMES_DASHBOARD_PORT=8765 \
    HERMES_DASHBOARD_ALLOW_LAN=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY hermes-agency ./hermes-agency
COPY scripts ./scripts
COPY docker ./docker
COPY --from=dashboard-web /app/hermes-agency/dashboard/dist ./hermes-agency/dashboard/dist

RUN python -m pip install --upgrade pip \
    && python -m pip install -e .

VOLUME ["/data/hermes"]
EXPOSE 8765
CMD ["python", "docker/run-dashboard.py"]
