"""
Подключение к базе данных (SQLite для старта, можно заменить на Postgres,
просто поменяв DATABASE_URL — SQLModel/SQLAlchemy работают одинаково).
"""
import os
from sqlalchemy import event
from sqlmodel import SQLModel, create_engine, Session

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "indie_tracker.db")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

# Многие облачные провайдеры (Render, Heroku и др.) выдают URL с префиксом "postgres://",
# который в SQLAlchemy 1.4+ требует замены на "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_SQLITE = DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if IS_SQLITE else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)

if IS_SQLITE:
    # WAL вместо дефолтного rollback-журнала: читатели (/api/games — почти
    # каждый заход на сайт) больше не блокируются на время, пока сборщик раз
    # в 6 часов пишет находки, и наоборот — без этого конкурентный доступ на
    # SQLite нет-нет да ловит "database is locked". Особенно актуально
    # теперь, когда файл базы переезжает на persistent disk на Render вместо
    # мимолётного локального SQLite для разработки.
    @event.listens_for(engine, "connect")
    def _enable_wal(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def init_db():
    SQLModel.metadata.create_all(engine)


def get_db_path():
    """
    Filesystem path of the sqlite file behind DATABASE_URL, or None for a
    non-sqlite DATABASE_URL (e.g. Postgres) — used to read the file's own
    mtime as a cheap "when was this last written to" signal, since every
    ingestion run (manual collect_now.py or the 6-hourly scheduler) commits
    to it. Resolved relative to this file, not the process's cwd, so it
    still finds indie_tracker.db regardless of where uvicorn was started
    from.
    """
    prefix = "sqlite:///"
    if not DATABASE_URL.startswith(prefix):
        return None
    path = DATABASE_URL[len(prefix):]
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    return path


def get_session():
    with Session(engine) as session:
        yield session
