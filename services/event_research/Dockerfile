FROM python:3.13.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace/services/event_research
COPY services/event_research/pyproject.toml services/event_research/constraints.txt ./
COPY services/event_research/app ./app
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10011 --create-home event_research
COPY services/event_research/alembic.ini ./
COPY services/event_research/migrations ./migrations
COPY contracts /workspace/contracts
COPY config/event_research /workspace/config/event_research
USER 10011
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8011", "--no-access-log"]

FROM base AS test
USER root
RUN pip install --no-cache-dir -c constraints.txt pytest pytest-asyncio
COPY services/event_research/tests ./tests
USER 10011
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
