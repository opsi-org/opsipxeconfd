# -*- coding: utf-8 -*-

# opsipxeconfd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2013-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

"""
opsipxeconfd
"""

import grp
import os
import stat
from socket import AF_UNIX, SOCK_STREAM
from socket import error as socket_error
from socket import socket
from threading import Lock, Thread
from time import asctime, localtime, sleep, time
from typing import Any

from opsicommon.client.opsiservice import ServiceClient
from opsicommon.config.opsi import OpsiConfig  # type: ignore[import]
from opsicommon.exceptions import (
	LicenseMissingError,
	OpsiServiceAuthenticationError,
	OpsiServiceError,
	OpsiServiceVerificationError,
)
from opsicommon.logging import get_logger, log_context, secret_filter
from opsicommon.objects import Host, NetbootProduct, ProductOnClient
from opsicommon.types import forceHostId, forceStringList

from .logging import init_logging
from .pxeconfigwriter import PXEConfigWriter
from .util import ClientConnection, StartupTask

ELILO_X86 = "x86"
ELILO_X64 = "x64"

logger = get_logger()
opsi_config = OpsiConfig()


class Opsipxeconfd(Thread):  # pylint: disable=too-many-instance-attributes
	"""
	class Opsipxeconfd

	This class handles installation of NetbootProducts via network.
	"""

	def __init__(self, config: dict[str, Any]) -> None:
		"""
		Opsipxeconfd constructor.

		This constructor initializes a new Opsipxeconfd instance.
		Settings are set according to the proveded config dictionary.

		:param config: Opsipxeconfd configuration dictionary as loaded from file
			or specified on command line at execution
		:type config: Dict
		"""
		Thread.__init__(self)

		self.config = config
		self._running = False
		self.error: str | None = None
		self._socket: socket | None = None
		self._client_connection_lock = Lock()
		self._pxe_config_writers_lock = Lock()
		self._client_connections: list[ClientConnection] = []
		self._pxe_config_writers: list[PXEConfigWriter] = []
		self._startup_task: StartupTask | None = None
		self._opsi_admin_gid = grp.getgrnam(opsi_config.get("groups", "admingroup"))[2]
		self._secure_boot_module = False
		self._uefi_module = False
		self.service = ServiceClient(
			address=opsi_config.get("service", "url"),
			username=opsi_config.get("host", "id"),
			password=opsi_config.get("host", "key"),
			jsonrpc_create_objects=True,
			ca_cert_file="/etc/opsi/ssl/opsi-ca-cert.pem",
		)
		logger.comment("opsi pxe configuration service starting")

	def set_config(self, config: dict[str, Any]) -> None:
		"""
		Sets new configuration.

		This method expects a configuration dictionary and overrides
		the existing configuration with the new one.

		:param config: Opsipxeconfd configuration dictionary.
		:type config: Dict
		"""
		logger.notice("Got new config")
		self.config = config

	def is_running(self) -> bool:
		"""
		Execution status request.

		This method returns whether this instance of Opsipxeconfd is running.

		:returns: True if Opsipxeconfd is running, else False.
		:rtype: bool
		"""
		return self._running

	def stop(self) -> None:
		"""
		Request to stop Opsipxeconfd thread.

		This method requests a stop and join for the associated
		StartupTask instance. Afterwards it requests a stop
		for the current Opsipxeconfd thread.
		"""
		logger.notice("Stopping opsipxeconfd")

		if self._startup_task:
			try:
				self._startup_task.stop()
				self._startup_task.join(10)
			except RuntimeError:
				pass  # Probably not yet started
			except Exception as err:  # pylint: disable=broad-except
				logger.debug("Error during stop: %s", err, exc_info=True)

		logger.info("Stopping pxe config writers")
		for pcw in self._pxe_config_writers:
			try:  # pylint: disable=loop-try-except-usage
				logger.debug("Stopping %s", pcw)  # pylint: disable=loop-global-usage
				pcw.stop()
			except Exception as err:  # pylint: disable=broad-except
				logger.error("Failed to stop %s: %s", pcw, err, exc_info=True)  # pylint: disable=loop-global-usage

		for pcw in self._pxe_config_writers:
			logger.debug("Waiting for %s to stop", pcw)  # pylint: disable=loop-global-usage
			pcw.join(5)

		self._running = False

		if self._socket:
			try:
				self._socket.close()
			except Exception as err:  # pylint: disable=broad-except
				logger.error("Failed to close socket: %s", err)

	def reload(self) -> None:
		"""
		Reloads the Opsipxeconfd config.

		This method reinitializes logging for the
		(possibly altered) configuration dictionary.
		Then recreates the backend and the socket.
		"""
		logger.notice("Reloading opsipxeconfd")
		init_logging(self.config)
		self._get_licensing_info()
		self._create_socket()

	def _get_licensing_info(self) -> None:
		info = self.service.jsonrpc("backend_getLicensingInfo")
		logger.debug("Got licensing info from service: %s", info)
		if "uefi" in info["available_modules"]:
			self._uefi_module = True
		if "secureboot" in info["available_modules"]:
			self._secure_boot_module = True
		logger.info(
			"uefi module is %s, secureboot module is %s",
			"enabled" if self._uefi_module else "disabled",
			"enabled" if self._secure_boot_module else "disabled",
		)

	def _create_socket(self) -> None:
		"""
		Creates new Socket.

		This method instantiates a new UnixSocket and binds it to a file
		specified in config['port']. Theoretically this UnixSocket could
		be substituted by a network socket bound to a network port.
		"""
		self._create_unix_socket()

	def _create_unix_socket(self) -> None:
		"""
		Creates new UnixSocket.

		This method instantiates a new UnixSocket and binds it to a file
		specified in config['port']. Access rights are adjusted for the
		resulting socket file.
		"""
		logger.notice("Creating unix socket %s", self.config["port"])
		if os.path.exists(self.config["port"]):
			os.unlink(self.config["port"])
		self._socket = socket(AF_UNIX, SOCK_STREAM)
		try:
			self._socket.bind(self.config["port"])
		except Exception as err:
			raise Exception(f"Failed to bind to socket '{self.config['port']}': {err}") from err
		self._socket.settimeout(0.1)
		self._socket.listen(self.config["maxConnections"])

		self._set_access_rights_for_socket(self.config["port"])

	def _set_access_rights_for_socket(self, path: str) -> None:
		"""
		Sets access rights for UnixSocket.

		This method adjusts the permissions of a UnixSocket file to o*66
		and gives group ownership to opsiadmin group.

		:param path: Path of the UnixSocket.
		:type path: str
		"""
		logger.debug("Setting rights on socket '%s'", path)
		mode = os.stat(path)[0]
		# Adding read + write access for group and other.
		os.chmod(path, mode | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
		os.chown(path, -1, self._opsi_admin_gid)
		logger.debug("Done setting rights on socket '%s'", path)

	def _get_connection(self) -> None:
		"""
		Creates and starts ClientConnection thread.

		This method initializes a ClientConnection thread, passing
		the associated socket and clientConnectionCallback.
		Afterwards, the ClientConnection is run.
		"""
		assert self._socket
		try:
			sock, _ = self._socket.accept()
		except socket_error as err:
			if not self._running:
				return
			if err.args[0] == "timed out" or err.args[0] == 11:
				return

			logger.debug("Socket error: %s", err)
			raise err
		logger.notice("Got connection from client")

		client_connection = None
		logger.info("Creating thread for connection %d", len(self._client_connections) + 1)
		try:
			client_connection = ClientConnection(self, sock, self.client_connection_callback)
			with self._client_connection_lock:
				self._client_connections.append(client_connection)
			client_connection.start()
			logger.debug("Connection %s started.", client_connection.name)
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to create control connection: %s", err, exc_info=True)

			if client_connection:
				with self._client_connection_lock:
					try:
						self._client_connections.remove(client_connection)
					except ValueError:
						pass  # Element not in list

	def run(self) -> None:
		"""
		Opsipxeconfd thread main method.

		This method is run on Opsipxeconfd execution.
		It creates backend, StartupTask and socket.
		"""
		with log_context({"instance": "Opsipxeconfd"}):
			self._running = True
			logger.notice("Starting opsipxeconfd main thread")
			try:
				max_attempts = 3
				for attempt in range(1, max_attempts + 1):
					try:  # pylint: disable=loop-try-except-usage
						logger.notice(  # pylint: disable=loop-global-usage
							"Connecting to opsi service at %r (attempt %d)", self.service.base_url, attempt
						)
						self.service.connect()
					except (OpsiServiceAuthenticationError, OpsiServiceVerificationError):  # pylint: disable=loop-invariant-statement
						raise
					except OpsiServiceError as err:  # pylint: disable=broad-except
						message = f"Failed to connect to opsi service at {self.service.base_url!r}: {err}"  # pylint: disable=loop-invariant-statement
						if attempt == max_attempts:
							raise RuntimeError(message) from err

						message = f"{message}, retry in 5 seconds."
						logger.warning(message)  # pylint: disable=loop-global-usage
						sleep(5)

				logger.info("Setting needed boot configurations")
				self._startup_task = StartupTask(self)
				self._startup_task.start()
				self._create_socket()
				while self._running:
					self._get_connection()
				logger.notice("Opsipxeconfd main thread exiting...")
			except Exception as err:  # pylint: disable=broad-except
				logger.error(err, exc_info=True)
				self.error = str(err)
			finally:
				self.service.disconnect()
				self._running = False

	def client_connection_callback(self, connection: ClientConnection) -> None:
		"""
		Callback method for ClientConnection.

		This method is meant to be hooked to ClientConnection instances.
		Upon end of their run method, this is called.
		It logs the time of life of the Clientconnection and removes the
		ClientConnection instance, so that it can be garbage collected.

		:param connection: ClientConnection that the callback is hooked to.
		:type connection: ClientConnection
		"""
		logger.info("ClientConnection %s finished (took %0.3f seconds)", connection.name, (time() - connection.start_time))

		try:
			with self._client_connection_lock:
				try:
					self._client_connections.remove(connection)
				except ValueError:
					pass  # Connection not in list

			logger.debug("ClientConnection '%s' removed", connection.name)
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to remove ClientConnection: %s", err)

	def pxe_config_writer_callback(self, pcw: PXEConfigWriter) -> None:
		"""
		Callback for PXEConfigWriter

		This method is hooked to a PXEConfigWriter instance.
		It is run at the end of PXEConfigWriter thread execution.
		The PXEConfigWriter is removed from the Opsipxeconfd instance
		and backend and pxebootconfiguration are updated.

		:param pcw: PXEConfigWriter this method should be hooked to.
		:type pcw: PXEConfigWriter
		"""
		logger.info("PXEConfigWriter %s (for %s) finished (running for %0.3f seconds)", pcw.name, pcw.host_id, (time() - pcw.start_time))

		try:
			with self._pxe_config_writers_lock:
				try:
					self._pxe_config_writers.remove(pcw)
				except ValueError:
					pass  # Writer not in list
			logger.debug("PXE config writer removed")
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to remove PXE config writer: %s", err)

		# renew objects and check if anythin changes on service since callback
		try:
			product_on_client: ProductOnClient = sorted(
				self.service.jsonrpc(
					"productOnClient_getObjects",
					[
						[],
						{
							"productType": "NetbootProduct",
							"clientId": pcw.product_on_client.clientId,
							"productId": pcw.product_on_client.productId,
						},
					],
				),
				key=lambda poc: poc.modificationTime or "",
				reverse=True,
			)[0]
		except IndexError:
			return

		always = product_on_client.actionRequest == "always"
		product_on_client.setActionProgress("pxe boot configuration read")
		if pcw.template_file != self.config["pxeConfTemplate"] and not always:
			product_on_client.setActionRequest("none")
		self.service.jsonrpc("productOnClient_updateObjects", [product_on_client])
		if always:
			self.update_boot_configuration(pcw.host_id)

	def status(self) -> str:
		"""
		Returns status information.

		This method collects status information about a running
		Opsipxeconfd instance. The result is returned as a string.

		:returns: Status information about running Opsipxeconfd.
		:rtype: str
		"""
		logger.notice("Getting opsipxeconfd status")
		result = "opsipxeconfd status:\n"

		with self._client_connection_lock:
			result += f"{len(self._client_connections)} control connection(s) established\n"
			for idx, connection in enumerate(self._client_connections, start=1):
				result += f"    Connection {idx} established at: {asctime(localtime(connection.start_time))}\n"

		result += f"\n{len(self._pxe_config_writers)} boot configuration(s) set\n"
		for pcw in self._pxe_config_writers:
			result += (
				f"Boot config for client '{pcw.host_id}' (path '{pcw.pxefile}'; configuration {pcw.append}) "
				f"set since {asctime(localtime(pcw.start_time))}\n"
			)
		logger.notice(result)
		return result

	def remove_boot_configuration(self, host_id: str) -> str:
		try:
			self._remove_current_config_writers(host_id)
		except Exception as err:
			logger.error(err, exc_info=True)
			raise err
		return "Boot configuration removed"

	def update_boot_configuration(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements,inconsistent-return-statements
		self, host_id: str
	) -> str:
		"""
		Updates Boot Configuration.

		This method is called for a specific host. It updates the PXE boot
		configuration for it. For NetbootProducts with pending action requests,
		a PXEConfigWriter is created and run.

		:param host_id: fqdn of a host in the network.
		:type host_id: str
		"""
		try:
			host_id = forceHostId(host_id)
			logger.info("Updating PXE boot configuration for host '%s'", host_id)

			self._remove_current_config_writers(host_id)

			try:
				host = self.service.jsonrpc("host_getObjects", [[], {"id": host_id}])[0]
			except IndexError:
				logger.info("Host %r not found", host_id)
				return "Boot configuration updated"

			try:
				product_on_client = self.service.jsonrpc(
					"productOnClient_getObjects",
					[
						[],
						{
							"productType": "NetbootProduct",
							"clientId": host_id,
							"actionRequest": ["setup", "uninstall", "update", "always", "once", "custom"],
						},
					],
				)[0]
			except IndexError:
				logger.info("No netboot products with action requests for client '%s' found.", host_id)
				return "Boot configuration updated"

			depot_id = str(self.config["depotId"])

			logger.debug("Searching for product '%s' on depot '%s'", product_on_client.productId, depot_id)
			try:  # pylint: disable=loop-try-except-usage
				product_on_depot = self.service.jsonrpc(
					"productOnDepot_getObjects",
					[[], {"productType": "NetbootProduct", "productId": product_on_client.productId, "depotId": depot_id}],
				)[0]
			except IndexError:
				logger.warning("Product %s not available on depot '%s'", product_on_client.productId, depot_id)
				return "Boot configuration updated"

			try:  # pylint: disable=loop-try-except-usage
				product = self.service.jsonrpc(
					"product_getObjects",
					[
						[],
						{
							"type": "NetbootProduct",
							"id": product_on_depot.productId,
							"productVersion": product_on_depot.productVersion,
							"packageVersion": product_on_depot.packageVersion,
						},
					],
				)[0]
			except IndexError:
				logger.error("Product %s not found", product_on_depot)
				return "Boot configuration updated"

			pxe_config_template = self._get_pxe_config_template(product_on_client, product)
			logger.debug("Using pxe config template '%s'", pxe_config_template)

			pxe_config_name = self._get_name_for_pxe_config_file(host)

			pxefile = os.path.join(self.config["pxeDir"], pxe_config_name)
			if os.path.exists(pxefile):
				for pcw in self._pxe_config_writers:
					if pcw.pxefile == pxefile:
						if host.id == pcw.host_id:
							logger.notice(  # pylint: disable=loop-global-usage
								"PXE boot configuration '%s' for client '%s' already exists.", pxefile, host.id
							)
							return "Boot configuration kept"
						raise RuntimeError(
							f"PXE boot configuration '{pxefile}' already exists. Clients '{host.id}' and '{pcw.host_id}' using same address?"
						)
				logger.debug("PXE boot configuration '%s' already exists, removing.", pxefile)
				os.unlink(pxefile)

			service_address = self._get_config_service_address(host_id)

			# Append arguments
			append = {
				"pckey": host.getOpsiHostKey(),
				"hn": host_id.split(".")[0],
				"dn": ".".join(host_id.split(".")[1:]),
				"product": product.id,
				"macaddress": host.getHardwareAddress(),
				"service": service_address,
			}
			if append["pckey"]:
				secret_filter.add_secrets(append["pckey"])

			append.update(self._get_additional_bootimage_parameters(host_id))

			# Get product property states
			product_property_states = {
				property_id: ",".join(values)
				for property_id, values in self.service.jsonrpc(
					"productPropertyState_getValues", {"product_ids": [product.id], "object_ids": [host_id]}
				).items()
			}

			pxe_config_writer: PXEConfigWriter | None = None
			try:
				logger.info("Creating thread for pxeconfig %d", len(self._pxe_config_writers) + 1)
				pxe_config_writer = PXEConfigWriter(
					template_file=pxe_config_template,
					host_id=host_id,
					product_on_client=product_on_client,
					append=append,
					product_property_states=product_property_states,
					pxefile=pxefile,
					secure_boot_module=self._secure_boot_module,
					uefi_module=self._uefi_module,
					callback=self.pxe_config_writer_callback,
				)
				with self._pxe_config_writers_lock:
					self._pxe_config_writers.append(pxe_config_writer)
				pxe_config_writer.start()
				logger.notice("PXE boot configuration for host %s is now set at '%s'", host_id, pxefile)
				return "Boot configuration updated"
			except Exception as err:
				logger.error("Failed to create pxe config writer: %s", err)
				if pxe_config_writer:
					with self._pxe_config_writers_lock:
						try:
							self._pxe_config_writers.remove(pxe_config_writer)
						except ValueError:
							pass  # Writer not in list
				raise
		except Exception as err:
			logger.error(err, exc_info=True)
			raise err

	def _remove_current_config_writers(self, host_id: str) -> None:
		"""
		Remove PXEConfigWriters for host.

		This method removes all registered PXEConfigWriters that are registered
		for a given host.

		:param host_id: fqdn of the host for which PXEConfigWriters should be removed.
		:type host_id: str
		"""
		with self._pxe_config_writers_lock:
			current_pcws = [pcw for pcw in self._pxe_config_writers if pcw.host_id == host_id]

			for pcw in current_pcws:
				self._pxe_config_writers.remove(pcw)

		logger.debug("Removing %s existing config writers for '%s'", len(current_pcws), host_id)

		for pcw in current_pcws:
			pcw.stop()
			pcw.stopped_event.wait(5)
			logger.notice("PXE boot configuration for host '%s' removed", host_id)  # pylint: disable=loop-global-usage

	def _get_pxe_config_template(
		self, product_on_client: ProductOnClient, product: NetbootProduct
	) -> str:  # pylint: disable=too-many-branches
		"""
		Get pxe template to use.

		This method determines the pxe template file that should be used for a client
		specified by fqdn in host_id. This depends on the architecture and the type
		of NetbootProduct and action request.

		:rtype: str
		:returns: The absolute path to the template that should be used for the client.
		"""
		pxe_config_template = None
		if product.pxeConfigTemplate:
			pxe_config_template = product.pxeConfigTemplate
			logger.notice(
				"Special pxe config template '%s' will be used used for product '%s' (host '%s')",
				pxe_config_template,
				product.id,
				product_on_client.clientId,
			)

		if not pxe_config_template:
			logger.debug("Using default config template")
			pxe_config_template = self.config["pxeConfTemplate"]

		assert pxe_config_template

		if not os.path.isabs(pxe_config_template):  # Not an absolute path
			logger.debug("pxeConfigTemplate is not an absolute path.")
			pxe_config_template = os.path.join(os.path.dirname(self.config["pxeConfTemplate"]), pxe_config_template)
			logger.debug("pxeConfigTemplate changed to %s", pxe_config_template)

		return pxe_config_template

	@staticmethod
	def _get_name_for_pxe_config_file(host: Host) -> str:
		"""
		Gets network address information.

		This method requests the ipv4 and the hardware address of
		a host and returns it as string.

		:param host: Host instance to get network address information from.
		:type host: Host

		:returns: String containing network address information of the host.
		:rtype: str
		"""
		if host.systemUUID:
			logger.debug("Got system UUID '%s' for host '%s'", host.systemUUID, host.id)
			return host.systemUUID
		if host.hardwareAddress:
			logger.debug("Got hardware address '%s' for host '%s'", host.hardwareAddress, host.id)
			return f"01-{host.hardwareAddress.replace(':', '-')}"
		if host.ipAddress:
			logger.warning("Failed to get hardware address for host '%s', using ip address '%s'", host.id, host.ipAddress)
			return "%02X%02X%02X%02X" % tuple(  # pylint: disable=consider-using-generator,consider-using-f-string
				[int(i) for i in host.ipAddress.split(".")]
			)
		raise Exception(f"Neither system UUID, hardware address nor ip address known for host '{host.id}'")

	def _get_config_service_address(self, host_id: str) -> str:
		"""
		Returns the config serive address for `host_id`.

		This method requests the url of the configserver, ensures
		that it ends with /rpc and returns it as a string.

		:param host_id: id of a host.
		:type host_id: str

		:returns: url of the configserver.
		:rtype: str
		"""
		configs = self.service.jsonrpc("configState_getValues", {"config_ids": ["clientconfig.configserver.url"], "object_ids": [host_id]})
		address = (configs.get("clientconfig.configserver.url") or [None])[0]
		if not address:
			address = opsi_config.get("service", "url")
		if not address.endswith("/rpc"):
			address += "/rpc"
		return address

	def _get_additional_bootimage_parameters(self, host_id: str) -> dict[str, str]:
		"""
		Returns additional bootimage parameters.

		This method requests additional bootimage parameters set for host_id
		and yields them (generator!).

		:param host_id: fqdn of client.
		:type host_id: str
		:returns: key-value pairs as tuple (value possibly empty) as yield.
		:rtype: Tuple
		"""
		configs = self.service.jsonrpc("configState_getValues", {"config_ids": ["opsi-linux-bootimage.append"], "object_ids": [host_id]})
		values = configs.get("clientconfig.configserver.url") or []
		params = {}
		for value in forceStringList(values):
			key = value
			val = ""
			if "=" in val:
				key, val = value.split("=", 1)
			params[key.lower().strip()] = val.strip()
		return params
