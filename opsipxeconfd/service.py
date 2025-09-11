# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

import json
import os
import subprocess
from functools import lru_cache
from time import sleep

from opsicommon.client.opsiservice import OpsiServiceAuthenticationError, OpsiServiceError, OpsiServiceVerificationError, ServiceClient
from opsicommon.config.opsi import OpsiConfig
from opsicommon.logging import get_logger, secret_filter

from opsipxeconfd import __version__, get_depot_id

logger = get_logger()
opsi_config = OpsiConfig()


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


@lru_cache
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
		username=get_depot_id(),
		password=opsi_config.get("host", "key"),
		user_agent=f"opsipxeconfd {__version__}",
		ca_cert_file="/etc/opsi/ssl/opsi-ca-cert.pem",
		client_cert_file=client_cert_file,
		client_key_file=client_key_file,
		client_key_password=client_key_password,
		jsonrpc_create_objects=True,
		jsonrpc_create_methods=True,
	)
	max_attempts = 6
	for attempt in range(1, max_attempts + 1):
		try:
			logger.notice("Connecting to opsi service at %r (attempt %d)", service.base_url, attempt)
			service.connect()
			break
		except (OpsiServiceAuthenticationError, OpsiServiceVerificationError):
			raise
		except OpsiServiceError as err:
			message = f"Failed to connect to opsi service at {service.base_url!r}: {err}"
			if attempt == max_attempts:
				raise RuntimeError(message) from err

			message = f"{message}, retry in 5 seconds."
			logger.warning(message)
			sleep(5)
	return service
