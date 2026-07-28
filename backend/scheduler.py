"""
Регулярный запуск сбора данных. Источник — только YouTube
(Steam-модуль отключён: публичный storefront-эндпоинт оказался
нестабильным и не давал результатов; файл ingestion/steam.py
остался в проекте на случай, если захотите его починить и вернуть).

Частота подбирается под квоты YouTube API: 100 unit за один поиск
при лимите 10 000/день, поэтому 3 запроса в fetch_youtube_findings
* несколько запусков в день — комфортно.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session

from database import engine
from ingestion.youtube import fetch_youtube_findings

logger = logging.getLogger("scheduler")


def run_all_ingestion():
    with Session(engine) as session:
        for name, fn in (
            ("youtube", fetch_youtube_findings),
        ):
            try:
                results = fn(session)
                logger.info("%s: собрано %d находок", name, len(results))
            except Exception:
                logger.exception("Сбой при сборе данных с %s", name)


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_all_ingestion, "interval", hours=6, next_run_time=None)
    scheduler.start()
    return scheduler
