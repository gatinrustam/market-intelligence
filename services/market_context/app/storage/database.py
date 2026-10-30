from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_database(url: str):
    kwargs = {'pool_pre_ping': True}
    if url.startswith('mysql'):
        kwargs.update(pool_recycle=1800, isolation_level='READ COMMITTED',
                      connect_args={'connect_timeout': 5, 'read_timeout': 10, 'write_timeout': 10})
    engine = create_engine(url, **kwargs)
    return engine, sessionmaker(engine, expire_on_commit=False)
