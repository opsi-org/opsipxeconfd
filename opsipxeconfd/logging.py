# -*- coding: utf-8 -*-
"""
:copyright: uib GmbH <info@uib.de>
This file is part of opsi - https://www.opsi.org

:license: GNU Affero General Public License version 3
"""

from typing import Dict

from opsicommon.logging import (
	DEFAULT_FORMAT, DEFAULT_COLORED_FORMAT, logger, logging_config, handle_log_exception
)

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
		stderr_level = max(config.get("logLevelStderr"), config.get("logLevel"))
		file_level = max(config.get("logLevelFile"), config.get("logLevel"))
		if config["daemon"]:
			stderr_level = None
		logging_config(
					stderr_format=DEFAULT_COLORED_FORMAT,
					stderr_level=stderr_level,
					log_file=config["logFile"],
					file_format=DEFAULT_FORMAT,
					file_level=file_level,
					file_rotate_max_bytes=config.get("maxBytesLog", 0)*1000*1000,
					file_rotate_backup_count=config.get("backupCountLog")
		)
	except Exception as err:
		handle_log_exception(err)
