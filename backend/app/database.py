from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

if settings.database_url:
    engine = create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
else:
    engine = None
    SessionLocal = None
