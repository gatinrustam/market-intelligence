FROM python:3.13.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace/services/evaluation
COPY services/evaluation/pyproject.toml services/evaluation/constraints.txt ./
COPY services/evaluation/app ./app
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10007 --create-home evaluation
COPY services/evaluation/alembic.ini ./
COPY services/evaluation/migrations ./migrations
COPY contracts /workspace/contracts
USER 10007
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8007", "--no-access-log"]

FROM base AS test
USER root
RUN pip install --no-cache-dir -c constraints.txt pytest pytest-asyncio
COPY services/evaluation/tests ./tests
USER 10007
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
