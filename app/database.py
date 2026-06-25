from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

_url = settings.database_url
_is_sqlite = _url.startswith("sqlite")

engine = create_engine(
    _url,
    **(
        {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}
        if not _is_sqlite
        else {"connect_args": {"check_same_thread": False}}
    ),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
