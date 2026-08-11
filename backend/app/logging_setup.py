import logging
import sys

from app.config import settings

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format=_FORMAT,
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    # Библиотеки Google болтливы на INFO и засоряют логи на маленьком сервере
    for noisy in ("googleapiclient.discovery_cache", "googleapiclient.discovery", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
