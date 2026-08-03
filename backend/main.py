from dotenv import load_dotenv
load_dotenv()  # читает backend/.env и подставляет ключи в переменные окружения

import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI, Depends, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from sqlalchemy import func
import asyncio

from database import init_db, get_session, get_db_path
from models import Game, Finding
from scheduler import start_scheduler, run_all_ingestion
from ingestion.description_cleaner import clean_video_description

app = FastAPI(title="Indie Game Tracker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# доступные варианты фильтра по периоду публикации
PERIOD_DELTAS = {
    "today": timedelta(days=1),
    "3d": timedelta(days=3),
    "7d": timedelta(days=7),
    "14d": timedelta(days=14),
    "30d": timedelta(days=30),
}


@app.on_event("startup")
def on_startup():
    init_db()
    start_scheduler()  # автосбор каждые 6 часов продолжает работать в фоне,
                        # пока сервер запущен — это отдельно от ручного запуска
    # запускаем сбор данных сразу при старте сервера, не блокируя запуск
    asyncio.get_event_loop().run_in_executor(None, run_all_ingestion)


@app.get("/api/last-updated")
def last_updated(session: Session = Depends(get_session)):
    """
    Берет дату последней записи из таблицы Finding или Game,
    чтобы работать с любой базой данных (SQLite, PostgreSQL и др.).
    """
    latest = session.exec(select(func.max(Finding.found_at))).first()
    if not latest:
        latest = session.exec(select(func.max(Game.updated_at))).first()
    if not latest:
        path = get_db_path()
        if path and os.path.exists(path):
            mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
            return {"last_updated": mtime.isoformat()}
        return {"last_updated": None}

    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)

    return {"last_updated": latest.isoformat()}


@app.get("/api/ingest/run-now")
@app.post("/api/ingest/run-now")
def trigger_ingestion(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_all_ingestion)
    return {"status": "started", "message": "Сбор данных запущен в фоновом режиме"}


@app.get("/api/games")
def list_games(
    max_metric: Optional[int] = Query(
        None,
        description="показывать игры с просмотрами не выше этого числа; не передано — без ограничения",
    ),
    period: Optional[str] = Query(None, description="today | 3d | 7d | 30d"),
    session: Session = Depends(get_session),
):
    """
    Возвращает игры (источник — только YouTube) вместе с их лучшим
    (самым просматриваемым) видео, отфильтрованные по верхней границе
    просмотров и периоду публикации. Игры без единого найденного контакта
    не показываются.

    Сортировка, приоритет по контактам и избранное теперь считаются на
    стороне браузера (см. frontend/index.html) — сервер просто отдаёт
    отфильтрованный набор данных, без фиксированного порядка.
    """
    query = select(Finding).where(Finding.source_platform == "youtube")
    if max_metric is not None:
        query = query.where(Finding.metric_value <= max_metric)

    if period and period in PERIOD_DELTAS:
        cutoff = datetime.utcnow() - PERIOD_DELTAS[period]
        query = query.where(Finding.published_at >= cutoff)

    findings = session.exec(query).all()

    # группируем по игре, берём находку с максимальными просмотрами
    best_by_game: dict[int, Finding] = {}
    for f in findings:
        current = best_by_game.get(f.game_id)
        if current is None or f.metric_value > current.metric_value:
            best_by_game[f.game_id] = f

    game_ids = list(best_by_game.keys())
    if not game_ids:
        return []

    games = session.exec(select(Game).where(Game.id.in_(game_ids))).all()
    games_by_id = {g.id: g for g in games}

    result = []
    for game_id, finding in best_by_game.items():
        game = games_by_id.get(game_id)
        if not game:
            continue

        contacts = {
            "discord": game.discord_url,
            "steam": game.steam_url,
            "x": game.x_url,
            "instagram": game.instagram_url,
            "website": game.website_url,
        }
        if not any(contacts.values()):
            continue  # у игры нет ни одного найденного контакта — не показываем

        result.append({
            "id": game.id,
            "name": game.name,
            "contacts": contacts,
            "best_source": {
                "platform": finding.source_platform,
                "url": finding.source_url,
                "metric_type": finding.metric_type,
                "metric_value": finding.metric_value,
                "title": finding.title,
                "description": clean_video_description(finding.raw_text, finding.title),
                "published_at": finding.published_at.isoformat() if finding.published_at else None,
                "thumbnail_url": finding.thumbnail_url,
            },
        })

    return result


FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
