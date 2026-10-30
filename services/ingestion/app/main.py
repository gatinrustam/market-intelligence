import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.adapters.sources import make_adapter
from app.config import Settings, load_sources
from app.logging import configure_logging
from app.normalization.contract import Contract
from app.publishers.nats import JetStreamBus
from app.publishers.outbox import OutboxPublisher
from app.storage.database import make_database
from app.workers.ingest import Ingestor
from app.workers.supervisor import Supervisor


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        sources = load_sources(settings.sources_dir)
        contract = Contract(settings.schema_path)
        engine, sessions = make_database(settings.database_url.get_secret_value())
        bus = JetStreamBus(settings.nats_url.get_secret_value())
        async with httpx.AsyncClient() as client:
            adapters = {s.id: make_adapter(s, client, settings) for s in sources}
            supervisor = Supervisor(sources, adapters, Ingestor(sessions, contract),
                                    OutboxPublisher(sessions, bus, contract), settings.publisher_interval_seconds)
            app.state.engine, app.state.bus, app.state.supervisor = engine, bus, supervisor
            if settings.workers_enabled:
                supervisor.start()
            try:
                yield
            finally:
                await supervisor.stop()
                await bus.close()
                await asyncio.to_thread(engine.dispose)

    app = FastAPI(title='Ingestion Core', version='0.1.0', lifespan=lifespan)

    @app.get('/health')
    async def health():
        return {'status': 'alive'}

    @app.get('/ready')
    async def ready():
        def database_ready():
            try:
                with app.state.engine.connect() as conn:
                    version = conn.execute(text('SELECT version_num FROM alembic_version')).scalar()
                    conn.execute(text('SELECT id FROM outbox_events LIMIT 1'))
                    return version == '0001'
            except Exception:
                return False
        db, bus = await asyncio.gather(asyncio.to_thread(database_ready), app.state.bus.healthcheck())
        workers = all(not task.done() for task in app.state.supervisor.tasks)
        return JSONResponse({'database': db, 'jetstream': bus, 'workers': workers}, status_code=200 if db and bus and workers else 503)

    @app.get('/sources')
    async def sources_status():
        return list(app.state.supervisor.states.values())

    @app.get('/sources/{source_id}/health')
    async def source_health(source_id: str):
        state = app.state.supervisor.states.get(source_id)
        if state is None:
            raise HTTPException(404, 'Unknown source')
        return state

    return app


app = create_app()
