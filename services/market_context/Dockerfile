FROM python:3.13.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace/services/market_context
COPY services/market_context/pyproject.toml services/market_context/constraints.txt ./
COPY services/market_context/app ./app
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10005 --create-home market_context
COPY services/market_context/alembic.ini ./
COPY services/market_context/migrations ./migrations
COPY contracts /workspace/contracts
USER 10005
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004", "--no-access-log"]

FROM base AS test
USER root
RUN pip install --no-cache-dir -c constraints.txt pytest pytest-asyncio
COPY services/market_context/tests ./tests
USER 10005
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
