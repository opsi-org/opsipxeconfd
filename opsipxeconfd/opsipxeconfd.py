# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

import grp
import os
import secrets
from datetime import datetime
from pathlib import Path
from socket import AF_UNIX, SOCK_STREAM, socket
from socket import error as socket_error
from threading import Lock, Thread
from time import time
from typing import Any

from opsicommon.logging import get_logger, log_context, secret_filter
from opsicommon.objects import Host, OpsiClient, ProductOnClient
from opsicommon.types import forceHostId

from opsipxeconfd import PXE_CONFIG_DIR, get_depot_id, opsi_config
from opsipxeconfd._logging import init_logging
from opsipxeconfd.pxeconfigwriter import PXEConfigWriter
from opsipxeconfd.service import get_service_connection
from opsipxeconfd.template import get_template_context
from opsipxeconfd.util import ClientConnection, StartupTask

logger = get_logger()


class Opsipxeconfd(Thread):
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
		logger.comment("opsi pxe configuration service starting")
		self.service = get_service_connection()

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
			except Exception as err:
				logger.debug("Error during stop: %s", err, exc_info=True)

		logger.info("Stopping pxe config writers")
		for pcw in self._pxe_config_writers:
			try:
				logger.debug("Stopping %s", pcw)
				pcw.stop()
			except Exception as err:
				logger.error("Failed to stop %s: %s", pcw, err, exc_info=True)

		for pcw in self._pxe_config_writers:
			logger.debug("Waiting for %s to stop", pcw)
			pcw.join(5)

		self._running = False

		if self._socket:
			try:
				self._socket.close()
			except Exception as err:
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
		self._create_socket()

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
		path = Path(self.config["port"])
		if path.exists():
			path.unlink()
		self._socket = socket(AF_UNIX, SOCK_STREAM)
		try:
			self._socket.bind(str(path))
		except Exception as err:
			raise RuntimeError(f"Failed to bind to socket '{path}': {err}") from err
		self._socket.settimeout(0.1)
		self._socket.listen(self.config["maxConnections"])

		self._set_access_rights_for_socket(path)

	def _set_access_rights_for_socket(self, path: Path) -> None:
		"""
		Sets access rights for UnixSocket.

		This method adjusts the permissions of a UnixSocket file to o*66
		and gives group ownership to opsiadmin group.

		:param path: Path of the UnixSocket.
		:type path: Path
		"""
		logger.debug("Setting rights on socket '%s'", path)
		os.chown(path, -1, self._opsi_admin_gid)
		os.chmod(path, 0o660)
		if path.parent.name == "opsipxeconfd":
			os.chown(path.parent, -1, self._opsi_admin_gid)
			path.parent.chmod(0o750)
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

		logger.info("Client #%d connected to socket %s", len(self._client_connections) + 1, self.config["port"])

		client_connection = None
		try:
			client_connection = ClientConnection(self, sock, self.client_connection_callback)
			with self._client_connection_lock:
				self._client_connections.append(client_connection)
			client_connection.start()
			logger.debug("Connection %s started.", client_connection.name)
		except Exception as err:
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
				logger.info("Setting needed boot configurations")
				self._startup_task = StartupTask(self)
				self._startup_task.start()
				self._create_socket()
				while self._running:
					self._get_connection()
				logger.notice("Opsipxeconfd main thread exiting...")
			except Exception as err:
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
		except Exception as err:
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
		except Exception as err:
			logger.error("Failed to remove PXE config writer: %s", err)

		try:
			product_on_client: ProductOnClient = sorted(
				self.service.productOnClient_getObjects(  # type: ignore[attr-defined]
					productType="NetbootProduct",
					clientId=pcw.host_id,
					productId=pcw.product_id,
				),
				key=lambda poc: poc.modificationTime or "",
				reverse=True,
			)[0]
		except IndexError as err:
			logger.warning("No ProductOnClient found for host '%s' and product '%s': %s", pcw.host_id, pcw.product_id, err)
			return

		product_on_client.setActionProgress("pxe boot configuration read")
		if product_on_client.actionRequest != "always":
			product_on_client.setActionRequest("none")

		self.service.productOnClient_updateObjects([product_on_client])  # type: ignore[attr-defined]

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
				result += (
					f"    Connection {idx} established at: {datetime.fromtimestamp(connection.start_time).strftime('%Y-%m-%d %H:%M:%S')}\n"
				)

		result += f"\n{len(self._pxe_config_writers)} boot configuration(s) set\n"
		for pcw in self._pxe_config_writers:
			result += (
				f"Boot config for client '{pcw.host_id}' ({', '.join(str(f) for f in pcw.pxefiles)}) "
				f"set since {datetime.fromtimestamp(pcw.start_time).strftime('%Y-%m-%d %H:%M:%S')}\n"
			)
		logger.notice("Status:\n%s", result)
		return result

	def remove_boot_configuration(self, host_id: str) -> str:
		try:
			self._remove_current_config_writers(host_id)
		except Exception as err:
			logger.error(err, exc_info=True)
			raise err
		return "Boot configuration removed"

	def update_boot_configuration(self, host_id: str) -> str:
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
				host: OpsiClient = self.service.host_getObjects(id=host_id)[0]  # type: ignore[attr-defined]
			except IndexError:
				logger.info("Host %r not found", host_id)
				return "Boot configuration updated"

			if host.getType() != "OpsiClient":
				logger.error("Host %r is not an OpsiClient, but %s", host_id, host.getType())
				return "Boot configuration updated"

			try:
				product_on_client = self.service.productOnClient_getObjects(  # type: ignore[attr-defined]
					productType="NetbootProduct",
					clientId=host_id,
					actionRequest=["setup", "uninstall", "update", "always", "once", "custom"],
				)[0]
			except IndexError:
				logger.info("No netboot products with action requests for client '%s' found.", host_id)
				return "Boot configuration updated"

			depot_id = get_depot_id()

			logger.debug("Searching for product '%s' on depot '%s'", product_on_client.productId, depot_id)
			try:
				product_on_depot = self.service.productOnDepot_getObjects(  # type: ignore[attr-defined]
					productType="NetbootProduct", productId=product_on_client.productId, depotId=depot_id
				)[0]
			except IndexError:
				logger.warning("Product %s not available on depot '%s'", product_on_client.productId, depot_id)
				return "Boot configuration updated"

			try:
				product = self.service.product_getObjects(  # type: ignore[attr-defined]
					type="NetbootProduct",
					id=product_on_depot.productId,
					productVersion=product_on_depot.productVersion,
					packageVersion=product_on_depot.packageVersion,
				)[0]
			except IndexError:
				logger.error("Product %s not found", product_on_depot)
				return "Boot configuration updated"

			context = get_template_context(
				host=host, product_on_depot=product_on_depot, product_on_client=product_on_client, product=product
			)
			pxefiles = self._get_pxe_config_files(host, host_identifiers=context.config_states["netboot.host_identifiers"].str_values)

			stop_pxe_config_writers: set[PXEConfigWriter] = set()
			for pcw in self._pxe_config_writers:
				for pxefile in pxefiles:
					if pxefile in pcw.pxefiles:
						if host.id == pcw.host_id:
							stop_pxe_config_writers.add(pcw)
						else:
							raise RuntimeError(
								f"PXE boot configuration files {pxefiles} already exist. Clients '{host.id}' and '{pcw.host_id}' using same address?"
							)
			for pcw in stop_pxe_config_writers:
				pcw.stop()
				pcw.join(5)

			if context.config_states["netboot.use_host_onetime_password"].bool_value:
				logger.info("Using one time password for host %r", host_id)
				otp = secrets.token_hex(16)
				# Only send needed attributes to prevent a loop
				self.service.host_updateObjects([OpsiClient(id=host.id, oneTimePassword=otp)])  # type: ignore[attr-defined]
				context.linux.additional_cmdline_params["otp"] = otp
			else:
				logger.info("Using opsi host key for host %r", host_id)
				opsi_host_key = host.getOpsiHostKey()
				if opsi_host_key:
					secret_filter.add_secrets(opsi_host_key)
					context.linux.additional_cmdline_params["pckey"] = opsi_host_key
				else:
					logger.error("No opsi host key set for host %r", host_id)

			pxe_config_writer: PXEConfigWriter | None = None
			try:
				logger.info("Creating thread for pxeconfig (total threads: %d)", len(self._pxe_config_writers) + 1)
				pxe_config_writer = PXEConfigWriter(
					context=context,
					pxefiles=pxefiles,
					callback=self.pxe_config_writer_callback,
				)
				with self._pxe_config_writers_lock:
					self._pxe_config_writers.append(pxe_config_writer)

				pxe_config_writer.start()
				pxe_config_writer.ready_event.wait(15)
				if pxe_config_writer.error:
					raise pxe_config_writer.error

				logger.notice("PXE boot configuration for host %r is now set at %s", host_id, ", ".join(str(f) for f in pxefiles))
				return "Boot configuration updated"
			except Exception as err:
				logger.error("Failed to create pxe config for host %r: %s", host_id, err)
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
			logger.notice("PXE boot configuration for host '%s' removed", host_id)

	@staticmethod
	def _get_pxe_config_files(host: Host, host_identifiers: list[str] | None = None) -> list[Path]:
		pxe_config_path = Path(PXE_CONFIG_DIR)
		if not host_identifiers:
			host_identifiers = ["system_uuid", "mac_address"]
		file_names = []
		if host.systemUUID:
			logger.debug("Got system UUID '%s' for host '%s'", host.systemUUID, host.id)
			filename = f"{host.systemUUID}.cfg"
			if "system_uuid" in host_identifiers:
				file_names.append(pxe_config_path / filename)
			else:
				logger.debug(
					"Not adding config file '%s' for host '%s' because system_uuid is not set in host_identifiers", filename, host.id
				)
		if host.hardwareAddress:
			logger.debug("Got hardware address '%s' for host '%s'", host.hardwareAddress, host.id)
			filename = f"{host.hardwareAddress.replace(':', '-')}.cfg"
			if "mac_address" in host_identifiers:
				file_names.append(pxe_config_path / filename)
			else:
				logger.debug(
					"Not adding config file '%s' for host '%s' because mac_address is not set in host_identifiers", filename, host.id
				)
		if not file_names:
			if "mac_address" in host_identifiers and "system_uuid" in host_identifiers:
				raise RuntimeError(f"Neither system UUID nor hardware address known for host '{host.id}'")
			if "system_uuid" in host_identifiers:
				raise RuntimeError(f"System UUID not known for host '{host.id}'")
			if "mac_address" in host_identifiers:
				raise RuntimeError(f"Hardware address not known for host '{host.id}'")
		return file_names
