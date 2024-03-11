# -*- coding: utf-8 -*-

# opsipxeconfd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2013-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

"""
opsipxeconfd - setup
"""

import json
import os
import subprocess
from time import sleep

import passlib.hash  # type: ignore[import]
from opsicommon.client.opsiservice import (OpsiServiceAuthenticationError,
                                           OpsiServiceError,
                                           OpsiServiceVerificationError,
                                           ServiceClient)
from opsicommon.config.opsi import OpsiConfig
from opsicommon.exceptions import OpsiServiceConnectionError
from opsicommon.logging import get_logger, secret_filter
from opsicommon.server.rights import set_rights
from opsicommon.server.setup import \
    setup_users_and_groups as po_setup_users_and_groups

logger = get_logger()
opsi_config = OpsiConfig()


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


def get_opsiconfd_config() -> dict[str, str]:
	config = {"ssl_server_key": "", "ssl_server_cert": "", "ssl_server_key_passphrase": ""}
	try:
		proc = subprocess.run(["opsiconfd", "get-config"], shell=False, check=True, capture_output=True, text=True, encoding="utf-8")
		for attr, value in json.loads(proc.stdout).items():
			if attr in config.keys() and value is not None:
				config[attr] = value
				if attr == "ssl_server_key_passphrase":
					secret_filter.add_secrets(value)
	except Exception as err:
		logger.debug("Failed to get opsiconfd config %s", err)
	return config


def get_service_connection() -> ServiceClient:
	client_cert_file = None
	client_key_file = None
	client_key_password = None
	cfg = get_opsiconfd_config()
	logger.debug("opsiconfd config: %r", cfg)
	if (
		cfg["ssl_server_key"]
		and os.path.exists(cfg["ssl_server_key"])
		and cfg["ssl_server_cert"]
		and os.path.exists(cfg["ssl_server_cert"])
	):
		client_cert_file = cfg["ssl_server_cert"]
		client_key_file = cfg["ssl_server_key"]
		client_key_password = cfg["ssl_server_key_passphrase"]

	service = ServiceClient(
		address=opsi_config.get("service", "url"),
		username=opsi_config.get("host", "id"),
		password=opsi_config.get("host", "key"),
		ca_cert_file="/etc/opsi/ssl/opsi-ca-cert.pem",
		client_cert_file=client_cert_file,
		client_key_file=client_key_file,
		client_key_password=client_key_password,
	)
	max_attempts = 6
	for attempt in range(1, max_attempts + 1):
		try:
			logger.notice("Connecting to opsi service at %r (attempt %d)", service.base_url, attempt)
			service.connect()
			break
		except (OpsiServiceAuthenticationError, OpsiServiceVerificationError):
			raise
		except OpsiServiceError as err:  # pylint: disable=broad-except
			message = f"Failed to connect to opsi service at {service.base_url!r}: {err}"
			if attempt == max_attempts:
				raise RuntimeError(message) from err

			message = f"{message}, retry in 5 seconds."
			logger.warning(message)
			sleep(5)
	return service


def getConfigsFromService() -> tuple[str, list[str]]:
	service: ServiceClient = get_service_connection()
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
		return configserverUrl, appendConfigs.defaultValues

	except OpsiServiceConnectionError:
		pass
	finally:
		service.disconnect()
	return "", []


def patchMenuFile(config: dict) -> None:
	"""
	Patch the address to the `configServer` and a password hash into `menufile`.

	To find out where to patch we look for lines that starts with the
	given `searchString` (excluding preceding whitespace).

	"""

	configserverUrl, defaultAppendParams = getConfigsFromService()

	if defaultAppendParams or configserverUrl:
		linuxDefaultDict: dict[str, str | None] = {}
		linuxAppendDict: dict[str, str | None] = {}
		linuxNewlinesDict: dict[str, str | None] = {}
		try:
			pwhEntry = ""
			langEntry = ""
			for element in defaultAppendParams:
				if "bootimageRootPassword" in element:
					clearRootPassword = element.split("=", maxsplit=1 )[1]
					endcodedRootPassword = encode_password(clearRootPassword)
					pwhEntry = f"pwh={endcodedRootPassword}"
				if "pwh=" in element:
					pwhEntry = element
				if pwhEntry:
					pwhEntry = pwhEntry.replace("$", r"\$")
				if "lang=" in element:
					langEntry = element
			grubFiles = ["/grub.cfg"]
			if os.path.exists(config["pxeDir"] + "/grub-menu.cfg"):
				grubFiles.append("/grub-menu.cfg")
			for grubFile in grubFiles:
				newlines = []
				with open(config["pxeDir"] + grubFile, "r", encoding="utf-8") as readMenu:
					for line in readMenu:
						if line.strip().startswith("linux"):
							linuxAppendDict.clear()
							if not linuxDefaultDict:
								for element in line.split(" "):
									if "=" in element:
										linuxDefaultDict[element.split("=")[0].strip(" \n\r")] = element.split("=")[1].strip(" \n\r")
									else:
										linuxDefaultDict[element.strip(" \n\r")] = None
							if "pwh" in linuxDefaultDict:
								linuxDefaultDict.pop("pwh")
							if "service" in linuxDefaultDict:
								linuxDefaultDict.pop("service")
							if "lang" in linuxDefaultDict:
								linuxDefaultDict.pop("lang")
							linuxNewlinesDict = linuxDefaultDict.copy()
							for element in line.split(" "):
								if "=" in element:
									linuxAppendDict[element.split("=")[0].strip(" \n\r")] = element.split("=")[1].strip(" \n\r")
								else:
									linuxAppendDict[element.strip(" \n\r")] = None
							if "pwh" in linuxAppendDict:
								linuxAppendDict.pop("pwh")
							if "service" in linuxAppendDict:
								linuxAppendDict.pop("service")
							if "lang" in linuxAppendDict:
								linuxAppendDict.pop("lang")
							if configserverUrl:
								linuxNewlinesDict["service"] = configserverUrl
								logger.debug("Patching service in %r: %s", grubFile, configserverUrl)
							if pwhEntry:
								pwh = pwhEntry.split("=", maxsplit=1)[1]
								linuxNewlinesDict[pwhEntry.split("=")[0].strip(" \n\r")] = pwh
								logger.debug("Patching pwh in %r: %s", grubFile, pwh)
							if langEntry:
								linuxNewlinesDict["lang"] = langEntry.split("=")[1].strip(" \n\r")
								logger.debug("Patching lang in %r: %s", grubFile, langEntry.split("=")[1].strip(" \n\r"))
							for key, value in linuxAppendDict.items():
								if key not in linuxDefaultDict:
									linuxNewlinesDict[key] = value
							if not configserverUrl:
								logger.error("configserver URL not found for %r", configserverUrl)
							line = " ".join(k if v is None else f"{k}={v}" for k, v in linuxNewlinesDict.items()) + "\n"

						newlines.append(line)

				with open(config["pxeDir"] + grubFile, "w", encoding="utf-8") as writeMenu:
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
