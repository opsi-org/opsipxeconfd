# -*- coding: utf-8 -*-

# opsipxeconfd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2013-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

"""
opsipxeconfd - setup
"""

import os
import re
from typing import Dict

from opsicommon.config.opsi import OpsiConfig  # type: ignore[import]
from opsicommon.logging import get_logger
from opsicommon.server.rights import set_rights
from opsicommon.server.setup import setup_users_and_groups as po_setup_users_and_groups

logger = get_logger()

def patchMenuFile(service_address: str, config: Dict) -> None:
	"""
	Patch the address to the `configServer` into `menufile`.

	To find out where to patch we look for lines that starts with the
	given `searchString` (excluding preceding whitespace).

	"""
	newlines = []
	try:
		with open(config["pxeDir"]+"grub.cfg", "r", encoding="utf-8") as readMenu:
			for line in readMenu:
				if line.strip().startswith("linux"):
					if "service=" in line:
						line = re.sub(r"service=\S+", "", line.rstrip())
					newlines.append(f"{line.rstrip()} service={service_address}\n")
					continue

				newlines.append(line)

		with open(config["pxeDir"]+"grub.cfg", "w", encoding="utf-8") as writeMenu:
			writeMenu.writelines(newlines)
	except FileNotFoundError:
		logger.notice(config["pxeDir"]+"grub.cfg not found")


def setup_files(log_file: str) -> None:
	"""
	Setup for log file.

	This method creates a log file (and directories in its path if necessary).
	Afterwards permissions are set.

	:param log_file: Name and path of the logfile to set up.
	:type log_file: str
	"""
	logger.info("Setup files and permissions")
	log_dir = os.path.dirname(log_file)
	if not os.path.isdir(log_dir):
		os.makedirs(log_dir)
	set_rights(log_dir)


def setup(config: Dict) -> None:
	"""
	Setup method for opsipxeconfd.

	This method sets up the environment for the opsipxeconfd to run.
	It creates necessary users and groups, initializes the backend and log file.

	:param config: opsipxeconfd configuration dictionary as created by opsipxeconfdinit.
	:type config: Dict
	"""
	logger.notice("Running opsipxeconfd setup")
	po_setup_users_and_groups()
	setup_files(config["logFile"])
	opsi_config = OpsiConfig()
	address=opsi_config.get("service", "url")
	patchMenuFile(address, config)
