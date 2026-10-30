from pathlib import Path
from unittest.mock import AsyncMock

import httpx
from app.config import Settings
from app.main import create_app


async def test_health_sources_and_dependency_readiness(database):
    root = Path(__file__).resolve().parents[3]
    settings = Settings(sources_dir=root / 'config/sources', schema_path=root / 'contracts/news/raw/v1.schema.json',
                        workers_enabled=False)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/health')).json() == {'status': 'alive'}
            assert len((await client.get('/sources')).json()) >= 3
            assert (await client.get('/sources/unknown/health')).status_code == 404
            app.state.bus.healthcheck = AsyncMock(return_value=False)
            assert (await client.get('/ready')).status_code == 503
            app.state.bus.healthcheck = AsyncMock(return_value=True)
            assert (await client.get('/ready')).status_code == 200
