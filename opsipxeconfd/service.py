# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

import json
import os
import subprocess
import threading
from functools import lru_cache
from time import sleep
from typing import Callable

from opsicommon.client.opsiservice import (
	MessagebusListener,
	OpsiServiceAuthenticationError,
	OpsiServiceError,
	OpsiServiceVerificationError,
	ServiceClient,
)
from opsicommon.config.opsi import OpsiConfig
from opsicommon.logging import get_logger, secret_filter
from opsicommon.messagebus.message import ChannelSubscriptionRequestMessage, EventMessage, Message

from opsipxeconfd import GRUB_CFG_MAX_UPDATE_INTERVAL, __version__, get_depot_id

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


class CallbackDebouncer(threading.Thread):
	def __init__(self, interval: int) -> None:
		super().__init__(daemon=True)
		self._interval = interval
		self._callback: Callable | None = None
		self._triggered = False
		self._num_triggered = 0
		self._num_callbacks = 0
		self._should_stop = False
		self.start()

	def stop(self) -> None:
		self._should_stop = True

	def set_callback(self, callback: Callable | None) -> None:
		self._callback = callback

	def trigger(self) -> None:
		self._triggered = True
		self._num_triggered += 1

	def run(self) -> None:
		while not self._should_stop:
			if not self._triggered:
				sleep(1)
				continue

			for _ in range(self._interval):
				if self._should_stop:
					return
				sleep(1)

			if self._triggered and self._callback:
				self._num_callbacks += 1
				logger.debug(
					"CallbackDebouncer: executing callback (triggered %d times, called %d times)", self._num_triggered, self._num_callbacks
				)
				try:
					self._callback()
				except Exception as err:
					logger.error("CallbackDebouncer callback error: %s", err, exc_info=True)
				self._triggered = False


class PXEConfigMessagebusListener(MessagebusListener):
	def __init__(self) -> None:
		self._netboot_config_changed_callback_debouncer = CallbackDebouncer(GRUB_CFG_MAX_UPDATE_INTERVAL)
		super().__init__()

	def set_netboot_config_changed_callback(self, callback: Callable | None) -> None:
		self._netboot_config_changed_callback_debouncer.set_callback(callback)

	def netboot_config_changed(self) -> None:
		self._netboot_config_changed_callback_debouncer.trigger()

	def message_received(self, message: Message) -> None:
		if not isinstance(message, EventMessage):
			return

		if message.event in ("config_created", "config_updated", "config_deleted"):
			if (message.data.get("id") or "").startswith("netboot."):
				self.netboot_config_changed()

		elif message.event in ("configState_created", "configState_updated", "configState_deleted"):
			if (message.data.get("configId") or "").startswith("netboot.") and message.data.get("objectId", "") == get_depot_id():
				self.netboot_config_changed()


@lru_cache
def get_messagebus_listener() -> PXEConfigMessagebusListener:
	return PXEConfigMessagebusListener()


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

	service.messagebus.register_messagebus_listener(get_messagebus_listener())
	service.messagebus.connect(wait=True)
	service.messagebus.send_message(
		ChannelSubscriptionRequestMessage(
			sender="@",
			channel="service:messagebus",
			channels=[
				"event:config_created",
				"event:config_updated",
				"event:config_deleted",
				"event:configState_created",
				"event:configState_updated",
				"event:configState_deleted",
			],
			operation="add",
		)
	)
	return service
