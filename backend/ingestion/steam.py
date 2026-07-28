"""
Ищет новые релизы в Steam через недокументированный, но широко используемый
storefront search endpoint (без ключа), затем по каждому app id забирает
appdetails (даёт сайт разработчика) и HTML-страницу магазина (там в блоке
"Find the community" почти всегда лежат discord/x/instagram разработчика).

Метрика популярности для Steam — количество отзывов (recommendations.total),
это прокси на "количество просмотров/интерес", т.к. Steam не отдаёт просмотры страницы.
"""
import re
import time
from datetime import datetime

import requests
from sqlmodel import Session

from models import Finding
from ingestion.contact_extractor import extract_contacts
from ingestion.game_matcher import find_or_create_game

SEARCH_URL = "https://store.steampowered.com/search/results/"
APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STORE_PAGE_URL = "https://store.steampowered.com/app/{appid}/"

SEARCH_PARAMS = {
    "query": "",
    "start": 0,
    "count": 50,
    "sort_by": "Released_DESC",
    "category1": 998,  # Games
    "tags": 492,  # Indie tag
    "os": "win",
    "supportedlang": "english",
    "json": 1,
}


def _extract_appids(search_json: dict) -> list[str]:
    return re.findall(r'data-ds-appid="(\d+)"', search_json.get("results_html", ""))


def enrich_contacts_from_steam_page(steam_url: str, timeout: int = 15) -> dict:
    """
    Заходит на уже известную страницу игры в Steam (ссылку, которую нашли,
    например, в описании YouTube-видео) и пытается дособрать контакты —
    discord/x/instagram/сайт — из блока "Find the Community" на странице.
    Не имеет отношения к поиску новых релизов (fetch_steam_findings) и
    гораздо надёжнее: просто читает уже известный URL, ничего не ищет сама.
    """
    try:
        resp = requests.get(steam_url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return {}
    return extract_contacts(resp.text)



    resp = requests.get(SEARCH_URL, params=SEARCH_PARAMS, timeout=15)
    resp.raise_for_status()
    appids = _extract_appids(resp.json())[:max_apps]

    new_findings = []
    for appid in appids:
        time.sleep(request_delay)  # не долбить Steam слишком часто

        details_resp = requests.get(APPDETAILS_URL, params={"appids": appid}, timeout=15)
        details = details_resp.json().get(appid, {})
        if not details.get("success"):
            continue
        data = details["data"]

        store_page_resp = requests.get(STORE_PAGE_URL.format(appid=appid), timeout=15)
        page_text = store_page_resp.text

        contacts = extract_contacts(page_text)
        if data.get("website") and "website_url" not in contacts:
            contacts["website_url"] = data["website"]
        if "steam_url" not in contacts:
            contacts["steam_url"] = STORE_PAGE_URL.format(appid=appid)

        game = find_or_create_game(session, data["name"], contacts)

        review_count = data.get("recommendations", {}).get("total", 0)
        release_date_raw = data.get("release_date", {}).get("date", "")

        finding = Finding(
            game_id=game.id,
            source_platform="steam",
            source_url=STORE_PAGE_URL.format(appid=appid),
            title=data["name"],
            raw_text=data.get("short_description", ""),
            metric_type="reviews",
            metric_value=review_count,
            published_at=_parse_steam_date(release_date_raw),
        )
        session.add(finding)
        new_findings.append(finding)

    session.commit()
    return new_findings


def _parse_steam_date(raw: str):
    for fmt in ("%d %b, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None
