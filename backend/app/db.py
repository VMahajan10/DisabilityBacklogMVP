from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app import config


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    if url is None:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{config.DB_PATH}"
    eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    from sqlalchemy import event

    @event.listens_for(eng, "connect")
    def _sqlite_pragmas(dbapi_conn, _):  # background jobs write while the API reads
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    return eng


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(bind=None):
    from app import models  # noqa: F401  (register tables)

    from sqlalchemy import inspect, text

    bind = bind or engine
    Base.metadata.create_all(bind=bind)
    # Tiny additive migration for SQLite: add new nullable columns to existing tables.
    insp = inspect(bind)
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have and col.nullable:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(bind.dialect)}'))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
