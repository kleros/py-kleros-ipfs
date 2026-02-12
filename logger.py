"""
Generic logger setup to log to both file and console.
"""
import json
import logging
from datetime import datetime
import sys


class JsonFormatter(logging.Formatter):
    """Format log records as JSON with message, level, and other standard fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


def setup_logger(name, log_file: str = 'log.log', level=logging.INFO) -> logging.Logger:
    """
    Sets up a logger with the specified name, log file, and logging level.

    Args:
        name (str): The name of the logger.
        log_file (str): The file path where the log messages will be saved.
        level (int, optional): The logging level (e.g., logging.INFO, logging.DEBUG). Defaults to logging.INFO.

    Returns:
        logging.Logger: Configured logger instance.

    Example:
        logger = setupLogger('my_logger', 'my_log_file.log')
        logger.info('This is an info message')
    """
    formatter = JsonFormatter()

    if '.' in log_file:
        log_file = log_file.replace(
            '.', f'_{datetime.now().strftime("%Y-%m-%d")}.')
    else:
        log_file = log_file + f'_{datetime.now().strftime("%Y-%m-%d")}.log'
    handler = logging.FileHandler(log_file)
    handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.addHandler(console_handler)

    return logger
