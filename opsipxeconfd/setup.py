# -*- coding: utf-8 -*-

# opsipxeconfd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2013-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

"""
opsipxeconfd - setup
"""

import os
#import re
import passlib.hash # type: ignore[import]

from opsicommon.client.opsiservice import get_service_client, ServiceClient

from opsicommon.exceptions import OpsiServiceConnectionError
from opsicommon.logging import get_logger
from opsicommon.server.rights import set_rights
from opsicommon.server.setup import setup_users_and_groups as po_setup_users_and_groups

logger = get_logger()

def encode_password(clearPassword: str) -> str:
	"""
	Encode a password using sha512_crypt.

	"""
	while True:
		pwhash = passlib.hash.sha512_crypt.using(rounds=5000).hash(clearPassword)
		if not pwhash or "." in pwhash:
			print("Invalid hash, retrying")
		else:
			return pwhash

def getConfigsFromService() -> tuple[str, list[str]]:

	service: ServiceClient = get_service_client()
	configserverId: str | None = ""
	try:
		configs = service.jsonrpc("host_getObjects", params=[[], {"type": "OpsiConfigserver"}])[0]
		configserverId = configs.id or None
		logger.notice(f"Configserver id {configserverId}")
		configs = service.jsonrpc(
			"configState_getValues", {"config_ids": ["clientconfig.configserver.url"], "object_ids": [configserverId]}
		)
		configserverUrl = (configs.get(configserverId, {}).get("clientconfig.configserver.url") or [None])[0]
		if not configserverUrl:
			raise RuntimeError(f"Failed to get config server address for {configserverUrl!r}")
		if not configserverUrl.endswith("/rpc"):
			configserverUrl += "/rpc"

		appendConfigs = service.jsonrpc("config_getObjects", params=[[], {"id": "opsi-linux-bootimage.append"}])[0]
		return configserverUrl,appendConfigs.defaultValues

	except OpsiServiceConnectionError:
		pass
	finally:
		service.disconnect()
	return "",[]

def patchMenuFile(config: dict) -> None:
	"""
	Patch the address to the `configServer` and a password hash into `menufile`.

	To find out where to patch we look for lines that starts with the
	given `searchString` (excluding preceding whitespace).

	"""

	configserverUrl,defaultAppendParams = getConfigsFromService()

	if defaultAppendParams or configserverUrl:
		linuxDefaultDict: dict[str, str] = {}
		linuxAppendDict: dict[str, str] = {}
		linuxNewlinesDict: dict[str, str] = {}
		newlines = []
		try:
			pwhEntry = ""
			for element in defaultAppendParams:
				if "bootimageRootPassword" in element:
					clearRootPassword = element.split("=")[1]
					endcodedRootPassword = encode_password(clearRootPassword)
					pwhEntry = f"pwh={endcodedRootPassword}"
				if "pwh=" in element:
					pwhEntry = element
			with open(config["pxeDir"] + "/grub.cfg", "r", encoding="utf-8") as readMenu:
				for line in readMenu:
					if line.strip().startswith("linux"):
						linuxAppendDict.clear()
						if not linuxDefaultDict:
							for element in line.split(" "):
								if "=" in element:
									linuxDefaultDict[element.split("=")[0]] = element.split("=")[1].strip()
								else:
									linuxDefaultDict[element] = ""
						if "pwh" in linuxDefaultDict:
							linuxDefaultDict.pop("pwh")
						if "service" in linuxDefaultDict:
							linuxDefaultDict.pop("service")
						linuxNewlinesDict = linuxDefaultDict.copy()
						for element in line.split(" "):
							if "=" in element:
								linuxAppendDict[element.split("=")[0]] = element.split("=")[1].strip()
							else:
								linuxAppendDict[element] = ""
						if "pwh" in linuxAppendDict:
							linuxAppendDict.pop("pwh")
						if "service" in linuxAppendDict:
							linuxAppendDict.pop("service")
						if pwhEntry:
							linuxNewlinesDict[pwhEntry.split("=")[0]] = pwhEntry.split("=")[1].strip()
						if configserverUrl:
							linuxNewlinesDict["service"] = configserverUrl
						for key, value in linuxAppendDict.items():
							if key not in linuxDefaultDict:
								linuxNewlinesDict[key] = value
						if not configserverUrl:
							logger.error("configserver URL not found for %r", configserverUrl)
						print(linuxNewlinesDict)
						line = ""
						for key, value in linuxNewlinesDict.items():
							if value:
								line += key + '=' + value + ' '
							else:
								line += key + ' '
						line = line + '\n'
						print(line)

					newlines.append(line)

			with open(config["pxeDir"] + "/grub.cfg", "w", encoding="utf-8") as writeMenu:
				writeMenu.writelines(newlines)
		except FileNotFoundError:
			logger.error("%r/grub.cfg not found", config["pxeDir"])

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


def setup(config: dict) -> None:
	"""
	Setup method for opsipxeconfd.

	This method sets up the environment for the opsipxeconfd to run.
	It creates necessary users and groups, initializes the backend and log file.

	:param config: opsipxeconfd configuration dictionary as created by opsipxeconfdinit.
	:type config: dict
	"""
	logger.notice("Running opsipxeconfd setup")
	po_setup_users_and_groups()
	setup_files(config["logFile"])
	patchMenuFile(config)
