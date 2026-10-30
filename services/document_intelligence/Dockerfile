FROM python:3.13.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace/services/document_intelligence
COPY services/document_intelligence/pyproject.toml services/document_intelligence/constraints.txt ./
COPY services/document_intelligence/app ./app
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10009 --create-home document_intelligence
COPY services/document_intelligence/alembic.ini ./
COPY services/document_intelligence/migrations ./migrations
COPY contracts /workspace/contracts
COPY config/document_intelligence /workspace/config/document_intelligence
USER 10009
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8009", "--no-access-log"]

FROM base AS test
USER root
RUN pip install --no-cache-dir -c constraints.txt pytest pytest-asyncio
COPY services/document_intelligence/tests ./tests
USER 10009
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
