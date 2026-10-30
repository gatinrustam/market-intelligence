FROM python:3.13.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace/services/event_intelligence
COPY services/event_intelligence/pyproject.toml services/event_intelligence/constraints.txt ./
COPY services/event_intelligence/app ./app
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10008 --create-home event_intelligence
COPY services/event_intelligence/alembic.ini ./
COPY services/event_intelligence/migrations ./migrations
COPY contracts /workspace/contracts
COPY config/event_intelligence /workspace/config/event_intelligence
USER 10008
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8008", "--no-access-log"]

FROM base AS test
USER root
RUN pip install --no-cache-dir -c constraints.txt pytest pytest-asyncio
COPY services/event_intelligence/tests ./tests
USER 10008
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
