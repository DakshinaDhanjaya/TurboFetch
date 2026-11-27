import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_logging(log_dir: Path = None, level: str = "INFO") -> logging.Logger:
    if log_dir is None:
        log_dir = Path.home() / "AppData" / "Local" / "TurboFetch" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    root_logger = logging.getLogger("turbofetch")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.handlers.clear()
    
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    
    file_handler = RotatingFileHandler(
        log_dir / "turbofetch.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    return root_logger

def get_logger(name: str) -> logging.Logger:
    if name.startswith("turbofetch."):
        return logging.getLogger(name)
    elif name == "turbofetch":
        return logging.getLogger("turbofetch")
    return logging.getLogger(f"turbofetch.{name}")
