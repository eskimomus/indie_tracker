"""
Находит существующую игру по названию (нечёткое сравнение, чтобы
"Hollow Knight: Silksong" и "Silksong (Hollow Knight 2)" не плодили дубликаты)
или создаёт новую запись.
"""
import re
from rapidfuzz import fuzz
from sqlmodel import Session, select

from models import Game
from ingestion.contact_extractor import merge_contacts, Contacts

MATCH_THRESHOLD = 85  # 0-100, порог схожести названий


def normalize(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9а-яё\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def find_or_create_game(session: Session, name: str, contacts: Contacts | None = None) -> Game:
    norm = normalize(name)

    candidates = session.exec(select(Game)).all()
    best_match: Game | None = None
    best_score = 0
    for candidate in candidates:
        score = fuzz.token_sort_ratio(norm, candidate.normalized_name)
        if score > best_score:
            best_score, best_match = score, candidate

    if best_match and best_score >= MATCH_THRESHOLD:
        game = best_match
        if contacts:
            updated = merge_contacts(game.dict(), contacts)
            for key, value in updated.items():
                setattr(game, key, value)
    else:
        game = Game(name=name, normalized_name=norm, **(contacts or {}))
        session.add(game)

    session.commit()
    session.refresh(game)
    return game
