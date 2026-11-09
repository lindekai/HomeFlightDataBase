"""Einstiegspunkt: ``python -m recorder``."""

import os
import signal
import threading

from recorder.config import Config
from recorder.logjson import setup_logging
from recorder.main import run


def main() -> None:
    setup_logging()
    os.umask(0o002)  # Gruppe flightdb muss lesen (Abholung) und Verzeichnisse schreiben dürfen
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    run(Config.from_env(), stop)


if __name__ == "__main__":
    main()
