"""Shared application logger."""

from __future__ import annotations

import logging

LOGGER_NAME = "hiro"

logger = logging.getLogger(LOGGER_NAME)

if not logger.handlers:
	handler = logging.StreamHandler()
	formatter = logging.Formatter(
		fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
		datefmt="%Y-%m-%d %H:%M:%S",
	)
	handler.setFormatter(formatter)
	logger.addHandler(handler)
	logger.setLevel(logging.DEBUG)
	logger.propagate = False
