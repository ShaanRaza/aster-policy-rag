"""Logging helper shared by Lambda handlers and local scripts.

Centralising logger creation gives us three benefits:

1. One place to set the log format that CloudWatch will receive.
2. One place to honour the `LOG_LEVEL` environment variable (handy for
   bumping to DEBUG without redeploying).
3. Every module gets a logger named after itself, which makes
   CloudWatch lines easy to filter (`shared.ingestion_pipeline ...`).
"""

import logging
import os


def get_logger(name: str) -> logging.Logger:
    """Return a logger configured from the `LOG_LEVEL` environment variable.

    `name` should be `__name__` from the calling module so each module's
    logger is independently nameable.
    """
    # Read the desired level from the environment. Default to INFO so
    # CloudWatch shows useful progress without being too noisy.
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    # Translate the string ("INFO", "DEBUG", ...) into the numeric constant
    # used by the logging module. Fall back to INFO if someone sets a typo.
    numeric_level = getattr(logging, log_level, logging.INFO)

    # `basicConfig` installs a StreamHandler on the root logger the first
    # time it is called. Subsequent calls are no-ops, which is fine —
    # repeated calls happen because both Lambdas may import this helper
    # multiple times via different paths.
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Build the module-specific logger and set its level explicitly so it
    # picks up changes when this function is called after basicConfig.
    logger = logging.getLogger(name)
    logger.setLevel(numeric_level)

    # Lambda's runtime sometimes attaches its own handler at WARNING. Loop
    # over any root handlers and force them down to our chosen level so
    # DEBUG actually shows up when the env var asks for it.
    for handler in logging.getLogger().handlers:
        handler.setLevel(numeric_level)
    return logger
