"""
Logger setup for Trading System v4.
"""
import logging
from pathlib import Path


from logging.handlers import RotatingFileHandler

def setup_logger(name, log_file=None, level=logging.INFO, max_bytes=1024*1024, backup_count=3):
    formatter = logging.Formatter('[%(asctime)s][%(levelname)s] %(message)s')
    if log_file:
        handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.handlers:
        logger.addHandler(handler)
    return logger
