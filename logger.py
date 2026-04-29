import logging
import sys
from pathlib import Path

LOG_FILE = Path(__file__).parent / "jarvis.log"

def setup_logger() -> logging.Logger:
    logger = logging.getLogger("jarvis")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")

    # File handler — full debug log
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Stderr handler — warnings and above only
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.WARNING)
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger

log = setup_logger()
