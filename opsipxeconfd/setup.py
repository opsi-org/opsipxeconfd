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

from opsicommon.client.opsiservice import get_service_client, ServiceClient

from opsicommon.exceptions import OpsiServiceConnectionError
from opsicommon.logging import get_logger
from opsicommon.server.rights import set_rights
from opsicommon.server.setup import setup_users_and_groups as po_setup_users_and_groups

logger = get_logger()


def patchMenuFile(config: Dict) -> None:
	"""
	Patch the address to the `configServer` into `menufile`.

	To find out where to patch we look for lines that starts with the
	given `searchString` (excluding preceding whitespace).

	"""

	service: ServiceClient = get_service_client()
	configserverId: str | None = ""
	try:
		configs = service.jsonrpc("host_getObjects", params=[[], {"type": "OpsiConfigserver"}])[0]
		configserverId = configs.id or None
		logger.notice(f"Configserver id {configserverId}")
		configs = service.jsonrpc("configState_getValues", {"config_ids": ["clientconfig.configserver.url"], "object_ids": [configserverId]})
		configserverUrl = (configs.get(configserverId, {}).get("clientconfig.configserver.url") or [None])[0]
		if not configserverUrl:
			raise RuntimeError(f"Failed to get config server address for {configserverUrl!r}")
		if not configserverUrl.endswith("/rpc"):
			configserverUrl += "/rpc"
	except OpsiServiceConnectionError:
		pass
	finally:
		service.disconnect()
	newlines = []
	if configserverUrl:
		try:
			with open(config["pxeDir"] + "/grub.cfg", "r", encoding="utf-8") as readMenu:
				for line in readMenu:
					if line.strip().startswith("linux"):
						if "service=" in line:
							line = re.sub(r"service=\S+", "", line.rstrip())
						newlines.append(f"{line.rstrip()} service={configserverUrl}\n")
						continue

					newlines.append(line)

			with open(config["pxeDir"] + "/grub.cfg", "w", encoding="utf-8") as writeMenu:
				writeMenu.writelines(newlines)
		except FileNotFoundError:
			logger.error(config["pxeDir"] + "/grub.cfg not found")
	else:
		logger.error("configserver URL not found for %r", configserverUrl)


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
	# opsi_config = OpsiConfig()
	# address=opsi_config.get("service", "url")
	patchMenuFile(config)
