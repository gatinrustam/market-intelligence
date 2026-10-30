FROM python:3.13.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace/services/ingestion
COPY services/ingestion/pyproject.toml services/ingestion/constraints.txt ./
COPY services/ingestion/app ./app
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10001 --create-home ingestion
COPY services/ingestion/alembic.ini ./
COPY services/ingestion/migrations ./migrations
COPY contracts /workspace/contracts
COPY config /workspace/config
USER 10001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM base AS test
USER root
RUN pip install --no-cache-dir -c constraints.txt pytest pytest-asyncio
COPY services/ingestion/tests ./tests
USER 10001
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
