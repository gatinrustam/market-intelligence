FROM python:3.13.12-slim-bookworm AS dependencies
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2
WORKDIR /workspace/services/article_semantic
COPY services/article_semantic/pyproject.toml services/article_semantic/constraints.txt ./
COPY services/article_semantic/model-requirements.txt ./
RUN pip install --no-cache-dir -r model-requirements.txt && useradd --uid 10012 --create-home article_semantic

FROM dependencies AS base
ENV PYTHONPATH=/workspace/services/article_semantic
COPY services/article_semantic/app ./app
RUN pip install --no-cache-dir -c constraints.txt .
COPY services/article_semantic/alembic.ini ./
COPY services/article_semantic/migrations ./migrations
COPY contracts /workspace/contracts
COPY config/article_semantic /workspace/config/article_semantic
USER 10012
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8012", "--no-access-log"]

FROM base AS test
USER root
RUN pip install --no-cache-dir -c constraints.txt pytest pytest-asyncio
COPY services/article_semantic/tests ./tests
USER 10012
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
