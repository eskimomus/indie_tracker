from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Game(SQLModel, table=True):
    """
    Одна строка = одна игра. Контакты собираются сюда постепенно —
    из разных источников (YouTube-описание, Reddit-пост, Steam-страница),
    более новая непустая находка перезаписывает пустое поле.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    normalized_name: str = Field(index=True)  # для fuzzy-матчинга находок между собой

    discord_url: Optional[str] = None
    steam_url: Optional[str] = None
    x_url: Optional[str] = None
    instagram_url: Optional[str] = None
    website_url: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Finding(SQLModel, table=True):
    """
    Одна строка = одно упоминание игры на конкретной площадке
    (трейлер на YouTube, пост в Reddit, страница в Steam).
    Именно по этой таблице фильтруем по просмотрам/апвоутам и площадке.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    game_id: int = Field(foreign_key="game.id", index=True)

    source_platform: str = Field(index=True)  # "youtube" | "reddit" | "steam"
    source_url: str
    title: str
    raw_text: str = ""  # описание/тело поста, откуда парсили контакты

    metric_type: str  # "views" | "upvotes" | "followers" — что именно в metric_value
    metric_value: int = 0

    found_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: Optional[datetime] = None
    thumbnail_url: Optional[str] = None
