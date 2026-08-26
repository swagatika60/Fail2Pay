from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


# base class for all models
class Base(DeclarativeBase):
    pass


settings = get_settings()

# only create engine if database url is provided
if settings.database_url:
    engine = create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
else:
    engine = None
    SessionLocal = None


# dependency for fastapi - gives a db session per request
def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL not configured")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
