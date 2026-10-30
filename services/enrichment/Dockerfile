FROM python:3.13.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace/services/enrichment
COPY services/enrichment/pyproject.toml services/enrichment/constraints.txt ./
COPY services/enrichment/app ./app
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10002 --create-home enrichment
COPY services/enrichment/alembic.ini ./
COPY services/enrichment/migrations ./migrations
COPY contracts /workspace/contracts
COPY config/enrichment /workspace/config/enrichment
USER 10002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]

FROM base AS test
USER root
RUN pip install --no-cache-dir -c constraints.txt pytest pytest-asyncio
COPY services/enrichment/tests ./tests
USER 10002
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
