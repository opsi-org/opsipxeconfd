# -*- coding: utf-8 -*-
"""
:copyright: uib GmbH <info@uib.de>
This file is part of opsi - https://www.opsi.org

:license: GNU Affero General Public License version 3
"""

import traceback
import time
import sys
import os
from typing import Dict
import logging

import opsicommon.logging
from opsicommon.logging import logger
from logging.handlers import WatchedFileHandler, RotatingFileHandler

def init_logging(config : Dict) -> None:
	"""
	Initializes logging for opsipxeconfd.

	This method takes an opsipxeconfd configuration dictionary and initializes
	logging accordingly. A rotating file handler with appropriate settings
	is added to the logger. If the opsipxeconfd is not started as daemon, a handler
	for stderr is also added.

	:param config: opsipxeconfd configuration dictionary as created by opsipxeconfdinit.
	:type config: Dict
	"""
	try:
		logLevel = max(config.get("logLevel"), config.get("logLevel_stderr"), config.get("logLevel_file"))
		logLevel = logging._opsiLevelToLevel[logLevel]
		if config['logFile']:
			plain_formatter = logging.Formatter(opsicommon.logging.DEFAULT_FORMAT)
			formatter = opsicommon.logging.ContextSecretFormatter(plain_formatter)
			file_handler = RotatingFileHandler(
						config['logFile'],
						maxBytes=config['maxBytesLog'],
						backupCount=config['backupCountLog']
			)
			file_handler.setFormatter(formatter)
			file_handler.setLevel(logging._opsiLevelToLevel[config.get("logLevel_file")])
			logger.addHandler(file_handler)
		
		logger.setLevel(logLevel)		
		logging.captureWarnings(True)
		opsicommon.logging.logging_config(
					stderr_format = opsicommon.logging.DEFAULT_COLORED_FORMAT,
					stderr_level=logging._opsiLevelToLevel[config.get("logLevel_stderr")],
					file_level=logging._opsiLevelToLevel[config.get("logLevel_file")]
		)

		if config['daemon']:
			opsicommon.logging.logging.remove_all_handlers(handler_type=logging.StreamHandler)

	except Exception as exc:
		opsicommon.logging.handle_log_exception(exc)
