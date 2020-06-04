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

import logging

from logging import LogRecord, Formatter, StreamHandler
from logging.handlers import WatchedFileHandler, RotatingFileHandler
import colorlog

import OPSI.Logger

# from .utils import Singleton
# from .config import config

class Singleton(type):
	_instances = {}
	def __call__(cls, *args, **kwargs):
		if cls not in cls._instances:
			cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
		return cls._instances[cls]

DEFAULT_FORMAT = "%(log_color)s[%(opsilevel)d] [%(asctime)s.%(msecs)03d]%(reset)s %(message)s   (%(filename)s:%(lineno)d)"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SECRET_REPLACEMENT_STRING = '***secret***'

#logger = logging.getLogger('opsipxeconfd')
logger = logging.getLogger()
#redis_log_handler = None

logging.NONE = 0
logging.NOTSET = logging.NONE
logging.SECRET = 10
logging.CONFIDENTIAL = logging.SECRET
logging.TRACE = 20
logging.DEBUG2 = logging.TRACE
logging.DEBUG = 30
logging.INFO = 40
logging.NOTICE = 50
logging.WARNING = 60
logging.WARN = logging.WARNING
logging.ERROR = 70
logging.CRITICAL = 80
logging.ESSENTIAL = 90
logging.COMMENT = logging.ESSENTIAL

logging._levelToName = {
	logging.SECRET: 'SECRET',
	logging.TRACE: 'TRACE',
	logging.DEBUG: 'DEBUG',
	logging.INFO: 'INFO',
	logging.NOTICE: 'NOTICE',
	logging.WARNING: 'WARNING',
	logging.ERROR: 'ERROR',
	logging.CRITICAL: 'CRITICAL',
	logging.ESSENTIAL: 'ESSENTIAL',
	logging.NONE: 'NONE'
}

logging._nameToLevel = {
	'SECRET': logging.SECRET,
	'TRACE': logging.TRACE,
	'DEBUG': logging.DEBUG,
	'INFO': logging.INFO,
	'NOTICE': logging.NOTICE,
	'WARNING': logging.WARNING,
	'ERROR': logging.ERROR,
	'CRITICAL': logging.CRITICAL,
	'ESSENTIAL': logging.ESSENTIAL,
	'NONE': logging.NONE
}

logging._levelToOpsiLevel = {
	logging.SECRET: 9,
	logging.TRACE: 8,
	logging.DEBUG: 7,
	logging.INFO: 6,
	logging.NOTICE: 5,
	logging.WARNING: 4,
	logging.ERROR: 3,
	logging.CRITICAL: 2,
	logging.ESSENTIAL: 1,
	logging.NONE: 0
}

logging._opsiLevelToLevel = {
	9: logging.SECRET,
	8: logging.TRACE,
	7: logging.DEBUG,
	6: logging.INFO,
	5: logging.NOTICE,
	4: logging.WARNING,
	3: logging.ERROR,
	2: logging.CRITICAL,
	1: logging.ESSENTIAL,
	0: logging.NONE
}

LOG_COLORS = {
	'SECRET': 'thin_yellow',
	'TRACE': 'thin_white',
	'DEBUG': 'white',
	'INFO': 'bold_white',
	'NOTICE': 'bold_green',
	'WARNING': 'bold_yellow',
	'ERROR': 'red',
	'CRITICAL': 'bold_red',
	'ESSENTIAL': 'bold_cyan'
}

def secret(self, msg, *args, **kwargs):
	if self.isEnabledFor(logging.SECRET):
		self._log(logging.SECRET, msg, args, **kwargs)
logging.Logger.secret = secret
logging.Logger.confidential = secret

def trace(self, msg, *args, **kwargs):
	if self.isEnabledFor(logging.TRACE):
		self._log(logging.TRACE, msg, args, **kwargs)
logging.Logger.trace = trace
logging.Logger.debug2 = trace

def notice(self, msg, *args, **kwargs):
	if self.isEnabledFor(logging.NOTICE):
		self._log(logging.NOTICE, msg, args, **kwargs)
logging.Logger.notice = notice

def essential(self, msg, *args, **kwargs):
	if self.isEnabledFor(logging.ESSENTIAL):
		self._log(logging.ESSENTIAL, msg, args, **kwargs)
logging.Logger.essential = essential
logging.Logger.comment = essential

def logrecord_init(self, name, level, pathname, lineno, msg, args, exc_info, func=None, sinfo=None, **kwargs):
	self.__init_orig__(name, level, pathname, lineno, msg, args, exc_info, func=func, sinfo=sinfo, **kwargs)
	self.opsilevel = logging._levelToOpsiLevel.get(level, level)
	self.client_address = kwargs.get("client_address", "")

LogRecord.__init_orig__ = LogRecord.__init__
LogRecord.__init__ = logrecord_init

# Set default log level to ERROR early
logger.setLevel(logging.ERROR)

# Replace OPSI Logger
def opsi_logger_factory():
	return logger
OPSI.Logger.Logger = opsi_logger_factory

def setLogFile(logFile, currentThread=False, object=None):
	pass
logger.setLogFile = setLogFile

def setLogFormat(logFormat):
	pass
logger.setLogFormat = setLogFormat

def setConfidentialStrings(strings):
	secret_filter.clear_secrets()
	secret_filter.add_secrets(*strings)
logger.setConfidentialStrings = setConfidentialStrings

def addConfidentialString(string):
	secret_filter.add_secrets(string)
logger.addConfidentialString = addConfidentialString

def logException(e, logLevel=logging.CRITICAL):
	logger.log(level=logLevel, msg=e, exc_info=True)
logger.logException = logException
# /Replace OPSI Logger

def handle_log_exception(exc, record=None, log=True):
	print("Logging error:", file=sys.stderr)
	traceback.print_exc(file=sys.stderr)
	if not log:
		return
	try:
		logger.error(f"Logging error: {exc}", exc_info=True)
		if record:
			logger.error(record.__dict__)
			#logger.error(f"{record.msg} - {record.args}")
	except:
		pass


class SecretFilter(metaclass=Singleton):
	def __init__(self, min_length=6):
		self._min_length = min_length
		self.secrets = []
	
	def clear_secrets(self):
		self.secrets = []
	
	def add_secrets(self, *secrets):
		for secret in secrets:
			if secret and len(secret) >= self._min_length and not secret in self.secrets:
				self.secrets.append(secret)
	
	def remove_secrets(self, *secrets):
		for secret in secrets:
			if secret in self.secrets:
				self.secrets.remove(secret)

secret_filter = SecretFilter()

class SecretFormatter(object):
	def __init__(self, orig_formatter):
		self.orig_formatter = orig_formatter
	
	def format(self, record):
		msg = self.orig_formatter.format(record)
		for secret in secret_filter.secrets:
			msg = msg.replace(secret, SECRET_REPLACEMENT_STRING)
		return msg
	
	def __getattr__(self, attr):
		return getattr(self.orig_formatter, attr)

def init_logging(config):
	try:
		logger.handlers = []

		logLevel = max(config.get("logLevel"), config.get("logLevel_stderr"), config.get("logLevel_file"))
		logLevel = logging._opsiLevelToLevel[logLevel]
		
		if config['logFile']:
			formatter = logging.Formatter(
				config["logFormat"].replace("%(log_color)s", "").replace("%(reset)s", ""),
				datefmt=DATETIME_FORMAT
			)
			file_handler = RotatingFileHandler(config['logFile'], maxBytes=config['maxBytesLog'], backupCount=config['backupCountLog'])
			file_handler.setFormatter(formatter)
			file_handler.setLevel(config.get("logLevel_file"))
			logger.addHandler(file_handler)

		if not config['daemon']:
			formatter = colorlog.ColoredFormatter(
				config["logFormat"],
				log_colors=LOG_COLORS,
				datefmt=DATETIME_FORMAT
			)
			console_handler = StreamHandler(stream=sys.stderr)
			console_handler.setFormatter(formatter)
			console_handler.setLevel(config.get("logLevel_stderr"))
			logger.addHandler(console_handler)

		logger.setLevel(logLevel)		
		logging.captureWarnings(True)

	except Exception as exc:
		handle_log_exception(exc)
