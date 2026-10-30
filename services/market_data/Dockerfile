FROM python:3.13.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace/services/market_data
COPY services/market_data/pyproject.toml services/market_data/constraints.txt ./
COPY services/market_data/app ./app
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10004 --create-home market_data
COPY services/market_data/alembic.ini ./
COPY services/market_data/migrations ./migrations
COPY contracts /workspace/contracts
USER 10004
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003", "--no-access-log"]

FROM base AS test
USER root
RUN pip install --no-cache-dir -c constraints.txt pytest pytest-asyncio
COPY services/market_data/tests ./tests
USER 10004
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
