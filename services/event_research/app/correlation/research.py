"""Resume/replay the configured immutable correlation research policy."""
import json
from app.config import Settings
from app.storage.database import make_database
from app.correlation.domain import load_policy
from app.correlation.repository import CorrelationRepository

def main():
    settings = Settings()
    engine, sessions = make_database(settings.database_url.get_secret_value())
    repo = CorrelationRepository(sessions, load_policy(settings.correlation_rules_path))
    try:
        repo.register()
        processed = 0
        while repo.run_once():
            processed += 1
        print(json.dumps({'new_research_results_processed': processed, 'stats': repo.stats()}))
    finally:
        engine.dispose()

if __name__ == '__main__':
    main()
