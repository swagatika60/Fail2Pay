from app.database import Base, engine


def init_db() -> None:
    """create all tables in the database"""
    if engine is None:
        raise RuntimeError("DATABASE_URL not configured")

    # import all models so they register with Base
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def drop_all() -> None:
    """drop all tables - use carefully, mainly for testing"""
    if engine is None:
        raise RuntimeError("DATABASE_URL not configured")

    import app.models  # noqa: F401

    Base.metadata.drop_all(bind=engine)


# run directly to create tables
if __name__ == "__main__":
    init_db()
    print("Database tables created.")
