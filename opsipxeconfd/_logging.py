# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

from typing import Dict

from opsicommon.logging import DEFAULT_COLORED_FORMAT, DEFAULT_FORMAT, LOG_NONE, handle_log_exception, logging_config

LOG_FILE = "/var/log/opsi/opsipxeconfd/opsipxeconfd.log"


def init_logging(config: Dict) -> None:
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
		stderr_level = max(config.get("logLevelStderr", LOG_NONE), config.get("logLevel", LOG_NONE))
		file_level = max(config.get("logLevelFile", LOG_NONE), config.get("logLevel", LOG_NONE))
		if config["daemon"]:
			stderr_level = None
		logging_config(
			stderr_format=DEFAULT_COLORED_FORMAT,
			stderr_level=stderr_level,
			log_file=LOG_FILE,
			file_format=DEFAULT_FORMAT,
			file_level=file_level,
			file_rotate_max_bytes=config.get("maxLogSize", 0) * 1000 * 1000,
			file_rotate_backup_count=config.get("keepRotatedLogs", 0),
		)
	except Exception as err:
		handle_log_exception(err)
