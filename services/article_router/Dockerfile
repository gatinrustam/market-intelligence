FROM python:3.13.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace/services/article_router
COPY services/article_router/pyproject.toml services/article_router/constraints.txt ./
COPY services/article_router/app ./app
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10010 --create-home article_router
COPY services/article_router/alembic.ini ./
COPY services/article_router/migrations ./migrations
COPY contracts /workspace/contracts
COPY config/article_router /workspace/config/article_router
USER 10010
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--no-access-log"]

FROM base AS test
USER root
RUN pip install --no-cache-dir -c constraints.txt pytest pytest-asyncio
COPY services/article_router/tests ./tests
USER 10010
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
