from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Database URL for SQLite at the project root
SQLALCHEMY_DATABASE_URL = "sqlite:///./app.db"

# connect_args={"check_same_thread": False} is required for SQLite in FastAPI
# because FastAPI can access the database from different worker threads.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    """
    Dependency generator to provide a database session for FastAPI routes.
    Ensures the session is closed after the request is finished.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """
    Creates all tables in the database. 
    Note: Ensure your models are imported before calling this!
    """
    # Import Base here if models are imported elsewhere, 
    # but normally you import your models in main.py before calling init_db()
    Base.metadata.create_all(bind=engine)