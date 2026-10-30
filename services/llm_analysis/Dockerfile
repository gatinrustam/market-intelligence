FROM python:3.13.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace/services/llm_analysis
COPY services/llm_analysis/pyproject.toml services/llm_analysis/constraints.txt ./
COPY services/llm_analysis/app ./app
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10006 --create-home llm_analysis
COPY services/llm_analysis/alembic.ini ./
COPY services/llm_analysis/migrations ./migrations
COPY contracts /workspace/contracts
USER 10006
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005", "--no-access-log"]

FROM base AS test
USER root
RUN pip install --no-cache-dir -c constraints.txt pytest pytest-asyncio
COPY services/llm_analysis/tests ./tests
USER 10006
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
