"""
Ищет видео по ключевым словам (трейлеры/анонсы инди-игр), достаёт просмотры
и парсит описание на предмет контактов.

Ищем в двух проходах на каждый запрос:
  - order="date"      — самые свежие видео (могут ещё не набрать просмотры)
  - order="viewCount"  — самые популярные видео за выбранный период
Это нужно, потому что YouTube Data API не даёт одновременно "новое и
популярное" одним вызовом — приходится комбинировать два сортировки.

Требует YOUTUBE_API_KEY (Google Cloud Console -> включить YouTube Data API v3).
Квота по умолчанию 10 000 unit/день; один search.list стоит 100 unit.
Точный расчёт квоты — в докстринге fetch_youtube_findings ниже.
"""
import os
import time
from datetime import datetime, timedelta
import requests
from googleapiclient.discovery import build
from sqlmodel import Session

from models import Finding
from ingestion.contact_extractor import extract_contacts, merge_contacts
from ingestion.game_matcher import find_or_create_game
from ingestion.steam import enrich_contacts_from_steam_page

OEMBED_URL = "https://www.youtube.com/oembed"

SEARCH_QUERIES = [
    "indie game trailer",
    "indie game announcement",
    "indie game reveal trailer",
]

SORT_ORDERS = ["date", "viewCount"]

GAMING_CATEGORY_ID = "20"  # категория YouTube "Игры" — отсекает не-игровой шум

# трейлеры почти всегда короче 4 минут — letsplay/обзоры/реакции обычно длиннее,
# так что ограничение по длительности само по себе отсекает много мусора
VIDEO_DURATION = "short"  # short = до 4 минут

# слова в заголовке, при наличии которых видео не считаем трейлером/анонсом
EXCLUDE_TITLE_KEYWORDS = (
    "review", "обзор", "react", "реакция", "реагир", "let's play", "lets play",
    "playthrough", "walkthrough", "прохождение", "gameplay stream",
    "full gameplay", "longplay", "стрим", "stream vod", "first impressions",
    "top 10", "top 5", "лучшие игры", "подборка", "compilation",
    "launch trailer",
)

# какие поля контактов считаем "желательными" — если после парсинга
# описания видео их не хватает, но есть ссылка на Steam, идём туда дозаполнять
_CONTACT_FIELDS = ("discord_url", "x_url", "instagram_url", "website_url")


def _client():
    api_key = os.environ["YOUTUBE_API_KEY"]
    return build("youtube", "v3", developerKey=api_key)


def _chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _looks_like_trailer(title: str) -> bool:
    title_lower = title.lower()
    return not any(keyword in title_lower for keyword in EXCLUDE_TITLE_KEYWORDS)


def _is_vertical_video(video_id: str) -> bool:
    """
    У YouTube Data API нет поля "ориентация видео", поэтому спрашиваем
    отдельный публичный сервис oEmbed — он отдаёт реальные пропорции
    (width/height) конкретного видео. Если высота больше ширины — это
    вертикальный ролик (обычно Shorts), его пропускаем.
    Если сервис не ответил — не исключаем видео из-за одной этой проверки.
    """
    try:
        resp = requests.get(
            OEMBED_URL,
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("height", 0) > data.get("width", 0)
    except requests.RequestException:
        return False


def fetch_youtube_findings(
    session: Session,
    lookback_days: int = 30,
    max_per_query: int = 50,
    max_pages: int = 3,
):
    """
    max_pages — сколько "страниц" по 50 результатов листать на каждую
    комбинацию запрос+сортировка. YouTube API физически не отдаёт больше
    50 результатов за один вызов — это лимит Google, не наш; чтобы получить
    больше, нужно листать через nextPageToken, что мы и делаем ниже.

    Квота: 3 запроса × 2 сортировки × max_pages вызовов × 100 unit.
    При max_pages=3 это 1800 unit за один прогон сбора — при лимите
    10 000/день можно запускать автосбор до 5 раз в день без проблем.
    """
    yt = _client()
    published_after = (datetime.utcnow() - timedelta(days=lookback_days)).isoformat("T") + "Z"

    # собираем уникальные id видео со всех комбинаций запрос x сортировка,
    # чтобы одно и то же видео не превратилось в два дубликата записи
    video_ids: set[str] = set()
    for query in SEARCH_QUERIES:
        for order in SORT_ORDERS:
            page_token = None
            for _ in range(max_pages):
                request_kwargs = dict(
                    q=query,
                    part="snippet",
                    type="video",
                    order=order,
                    videoCategoryId=GAMING_CATEGORY_ID,
                    videoDuration=VIDEO_DURATION,
                    publishedAfter=published_after,
                    maxResults=max_per_query,
                )
                if page_token:
                    request_kwargs["pageToken"] = page_token

                search_resp = yt.search().list(**request_kwargs).execute()
                video_ids.update(item["id"]["videoId"] for item in search_resp.get("items", []))

                page_token = search_resp.get("nextPageToken")
                if not page_token:
                    break  # больше страниц для этой комбинации нет — идём к следующей

    if not video_ids:
        session.commit()
        return []

    new_findings = []
    for chunk in _chunked(list(video_ids), 50):  # videos.list принимает максимум 50 id за раз
        videos_resp = yt.videos().list(
            part="snippet,statistics",
            id=",".join(chunk),
        ).execute()

        for video in videos_resp.get("items", []):
            snippet = video["snippet"]
            if not _looks_like_trailer(snippet["title"]):
                continue
            if _is_vertical_video(video["id"]):
                continue

            stats = video.get("statistics", {})
            views = int(stats.get("viewCount", 0))
            description = snippet.get("description", "")

            contacts = extract_contacts(description)

            # если в описании нашлась ссылка на Steam, но не хватает
            # других контактов — дозаполняем их со страницы игры в Steam
            missing_fields = [f for f in _CONTACT_FIELDS if not contacts.get(f)]
            if contacts.get("steam_url") and missing_fields:
                time.sleep(1)  # не долбить Steam слишком часто
                steam_contacts = enrich_contacts_from_steam_page(contacts["steam_url"])
                contacts = merge_contacts(contacts, steam_contacts)

            game_name = snippet["title"]  # можно улучшить регэкспом-очисткой от "| Trailer" и т.п.
            game = find_or_create_game(session, game_name, contacts)

            thumbnails = snippet.get("thumbnails", {})
            # берём среднее качество, если есть — иначе то, что дают (default всегда есть)
            thumbnail_url = (thumbnails.get("medium") or thumbnails.get("default") or {}).get("url")

            finding = Finding(
                game_id=game.id,
                source_platform="youtube",
                source_url=f"https://www.youtube.com/watch?v={video['id']}",
                title=snippet["title"],
                raw_text=description,
                metric_type="views",
                metric_value=views,
                published_at=datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")),
                thumbnail_url=thumbnail_url,
            )
            session.add(finding)
            new_findings.append(finding)

    session.commit()
    return new_findings
