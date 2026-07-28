"""
Достаёт ссылки на discord/steam/x/instagram/сайт из произвольного текста
(описание YouTube-видео, тело Reddit-поста, HTML Steam-страницы).
"""
import re
from typing import Optional, TypedDict


class Contacts(TypedDict, total=False):
    discord_url: str
    steam_url: str
    x_url: str
    instagram_url: str
    website_url: str


PATTERNS = {
    "discord_url": re.compile(r"https?://(?:www\.)?(?:discord\.gg|discord\.com/invite)/[A-Za-z0-9\-]+"),
    "steam_url": re.compile(r"https?://(?:store\.)?steampowered\.com/app/\d+[^\s)\]\"']*"),
    "x_url": re.compile(r"https?://(?:www\.)?(?:x\.com|twitter\.com)/[A-Za-z0-9_]+"),
    "instagram_url": re.compile(r"https?://(?:www\.)?instagram\.com/[A-Za-z0-9_.]+"),
}

# домены, которые точно не являются "сайтом разработчика" — чтобы не заносить в website_url
_EXCLUDED_DOMAINS = ("discord", "steampowered", "steamstatic", "steamcdn", "akamaihd",
                     "x.com", "twitter.com", "instagram",
                     "youtube.com", "youtu.be", "reddit.com",
                     # инфраструктура/трекинг, которая почти всегда стоит в
                     # начале HTML любой страницы (шрифты, аналитика, CDN) —
                     # без них _GENERIC_URL ниже подхватывал их вместо
                     # настоящего сайта разработчика, который обычно лежит
                     # гораздо ниже по странице
                     "googleapis.com", "gstatic.com", "googletagmanager.com",
                     "google-analytics.com", "doubleclick.net", "cloudflare.com",
                     "facebook.com", "fbcdn.net")

# ссылки на статические ресурсы (шрифты/скрипты/стили/картинки) — надёжный
# сигнал того, что ссылка не может быть "сайтом разработчика", независимо от
# домена (ловит любой CDN-ассет, а не только уже известные выше)
_STATIC_ASSET_EXT = re.compile(
    r"\.(?:css|js|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|eot|map)(?:[?#]|$)",
    re.IGNORECASE,
)

_GENERIC_URL = re.compile(r"https?://[^\s)\]\"']+")


def extract_contacts(text: str) -> Contacts:
    if not text:
        return {}

    found: Contacts = {}
    for field, pattern in PATTERNS.items():
        match = pattern.search(text)
        if match:
            found[field] = match.group(0)

    # Если явного "сайта" не было среди распознанных — берём первую ссылку,
    # которая не относится к соцсетям/платформам/статическим ресурсам выше.
    if "website_url" not in found:
        for url in _GENERIC_URL.findall(text):
            if any(domain in url for domain in _EXCLUDED_DOMAINS):
                continue
            if _STATIC_ASSET_EXT.search(url):
                continue
            found["website_url"] = url
            break

    return found


def merge_contacts(existing: dict, new: Contacts) -> dict:
    """Заполняет только пустые поля — не затирает уже найденные контакты."""
    for key, value in new.items():
        if not existing.get(key):
            existing[key] = value
    return existing
