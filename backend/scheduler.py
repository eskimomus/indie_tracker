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
    # Раньше здесь стоял next_run_time=None — по документации APScheduler
    # (apscheduler/schedulers/base.py, add_job) это добавляет задачу
    # НА ПАУЗЕ, а не просто откладывает первый запуск: ничего в проекте не
    # вызывает resume_job(), так что автосбор не работал вообще, ни разу.
    # IntervalTrigger сам по себе уже не запускает задачу немедленно: без
    # явного start_date его собственное значение по умолчанию —
    # datetime.now() + interval (apscheduler/triggers/interval.py), то
    # есть первый настоящий запуск и так будет через 6 часов после
    # старта сервера, дальше — каждые 6 часов от предыдущего запуска.
    scheduler.add_job(run_all_ingestion, "interval", hours=6)
    scheduler.start()
    return scheduler
