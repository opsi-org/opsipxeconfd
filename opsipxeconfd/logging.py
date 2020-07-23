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

import opsicommon.logging
import logging
from opsicommon.logging import logger
from logging.handlers import WatchedFileHandler, RotatingFileHandler
import colorlog

def init_logging(config):
	try:
		logLevel = max(config.get("logLevel"), config.get("logLevel_stderr"), config.get("logLevel_file"))
		#logLevel = logging._opsiLevelToLevel[logLevel]	# log level is handled by constants LOG_WARNING etc.
		if config['logFile']:
			plain_formatter = logging.Formatter(opsicommon.logging.DEFAULT_FORMAT)
			formatter = opsicommon.logging.ContextSecretFormatter(plain_formatter)
			file_handler = RotatingFileHandler(config['logFile'], maxBytes=config['maxBytesLog'], backupCount=config['backupCountLog'])
			file_handler.setFormatter(formatter)
			file_handler.setLevel(config.get("logLevel_file"))
			logger.addHandler(file_handler)

		#if config['daemon']:	#TODO
		#	opsicommon.logging.remove_all_handlers(handler_type=logging.StreamHandler)
		
		logger.setLevel(logLevel)		
		logging.captureWarnings(True)
		opsicommon.logging.set_format(stderr_format = opsicommon.logging.DEFAULT_COLORED_FORMAT)

	except Exception as exc:
		opsicommon.logging.handle_log_exception(exc)
