FROM python:3.13.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace/services/events
COPY services/events/pyproject.toml services/events/constraints.txt ./
COPY services/events/app ./app
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10003 --create-home events
COPY services/events/alembic.ini ./
COPY services/events/migrations ./migrations
COPY contracts /workspace/contracts
COPY config/events /workspace/config/events
USER 10003
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--no-access-log"]

FROM base AS test
USER root
RUN pip install --no-cache-dir -c constraints.txt pytest pytest-asyncio
COPY services/events/tests ./tests
USER 10003
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
