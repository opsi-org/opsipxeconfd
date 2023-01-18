# -*- coding: utf-8 -*-

# opsipxeconfd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2013-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

"""
opsipxeconfd - util
"""

from __future__ import annotations

import os
import time
from contextlib import closing, contextmanager
from shlex import split as shlex_split
from socket import socket
from threading import Thread
from typing import TYPE_CHECKING, Callable, Generator

from opsicommon.logging import get_logger
from opsicommon.system import ensure_not_already_running
from opsicommon.types import forceHostId, forceString

if TYPE_CHECKING:
	from opsipxeconfd.opsipxeconfd import Opsipxeconfd

ERROR_MARKER = "(ERROR)"

logger = get_logger()


@contextmanager
def pid_file(pid_file_path: str) -> Generator[None, None, None]:
	"""
	Maintain temporary PID file.

	Create a file containing the current pid for 'opsipxeconfd' at `pid_file_path`.
	Leaving the context will remove the file.

	:param pid_file_path: Path of the PID file to create.
	:type pid_file_path: str
	"""
	ensure_not_already_running("opsipxeconfd")

	logger.info("Creating pid file %r", pid_file_path)
	with open(pid_file_path, "w", encoding="utf-8") as file:
		file.write(str(os.getpid()))

	try:
		yield
	finally:
		if os.path.exists(pid_file_path):
			try:
				logger.debug("Removing pid file %r...", pid_file_path)
				os.unlink(pid_file_path)
				logger.info("Removed pid file %r", pid_file_path)
			except Exception as err:  # pylint: disable=broad-except
				logger.error("Failed to remove pid file %r: %s", pid_file_path, err)


class StartupTask(Thread):
	"""
	class StartupTask

	This class retrieves the initial boot configuration for the clients.
	"""

	def __init__(self, opsipxeconfd: Opsipxeconfd) -> None:
		"""
		StartupTask constructor.

		This constructor initializes a new StartupTask instance.
		The associated opsipxeconfd instance is stored.

		:param opsipxeconfd: Opsipxeconfd this StartupTask instance is issued by.
		:type opsipxeconfd: Opsipxeconfd
		"""
		Thread.__init__(self)
		self._opsipxeconfd = opsipxeconfd
		self._running = False
		self._should_stop = False

	def run(self) -> None:
		"""
		Main method of StartupTask thread.

		This method collects clientIds for which NetbootProducts exist with a
		related action request. For these clientIds the BootConfiguration of
		the opsipxeconfd is updated.
		"""
		self._running = True
		logger.notice("Start setting initial boot configurations")
		try:
			client_ids = [
				client_to_depot["clientId"]
				for client_to_depot in self._opsipxeconfd.service.jsonrpc(
					"configState_getClientToDepotserver",
					{"depotIds": [str(self._opsipxeconfd.config["depotId"])]},
				)
			]

			if client_ids:
				product_on_clients = self._opsipxeconfd.service.jsonrpc(
					"productOnClient_getObjects",
					[
						[],
						{
							"productType": "NetbootProduct",
							"clientId": client_ids,
							"actionRequest": ["setup", "uninstall", "update", "always", "once", "custom"],
						},
					],
				)

				for client_id in {poc.clientId for poc in product_on_clients}:
					if self._should_stop:
						return

					try:  # pylint: disable=loop-try-except-usage
						self._opsipxeconfd.update_boot_configuration(client_id)
					except Exception as err:  # pylint: disable=broad-except
						logger.error(  # pylint: disable=loop-global-usage
							"Failed to update PXE boot config for client '%s': %s", client_id, err
						)

			logger.notice("Finished setting initial boot configurations")
		except Exception as err:  # pylint: disable=broad-except
			logger.error(err, exc_info=True)
		finally:
			self._running = False

	def stop(self) -> None:
		"""
		StartupTask thread stop method.

		This method requests thread termination.
		"""
		self._should_stop = True


class ClientConnection(Thread):
	"""
	class ClientConnection

	This class handles a connection between opsipxeconfd and a single client.
	Communication is established via sockets. A callback can be registered
	to trigger an additional action.
	"""

	def __init__(self, opsipxeconfd: Opsipxeconfd, connection_socket: socket, callback: Callable | None = None) -> None:
		"""
		ClientConnection Constructor.

		This constructor initializes a new ClientConnection instance.
		A reference to the issuing opsipxeconfd is stored. Additionally the
		connection_socket for the communication is given and stored.
		Optionally a callback can be provided.
		The time of instance creation is stored.

		:param opsipxeconfd: Opsipxeconfd this StartupTask instance is issued by.
		:type opsipxeconfd: Opsipxeconfd
		:param connection_socket: Socket for communication.
		:type connection_socket: socket
		:param callback: callback method to be called after command execution.
		:type callback: Callable
		"""
		Thread.__init__(self)
		self._opsipxeconfd = opsipxeconfd
		self._socket = connection_socket
		self._callback = callback
		self._running = False
		self.start_time = time.time()

	def run(self) -> None:
		"""
		Main method of ClientConnection thread.

		This method receives a command via socket, executes it and the optionally
		executes the registered callback. The result of the command is sent back
		over the socket.
		"""
		self._running = True
		self._socket.settimeout(2.0)

		logger.debug("Receiving data...")
		with closing(self._socket):
			try:
				cmd = forceString(self._socket.recv(4096))
				logger.info("Got command '%s'", cmd)

				result = self._process_command(cmd)
				logger.info("Returning result '%s'", result)

				try:
					self._socket.send(result.encode("utf-8"))
				except Exception as err:  # pylint: disable=broad-except
					logger.warning("Sending result over socket failed: '%s'", err)
			finally:
				if self._running and self._callback:
					self._callback(self)

	def stop(self) -> None:
		"""
		ClientConnection thread stop method.

		This method requests thread termination. The socket is closed.
		"""
		self._running = False
		if self._socket:
			self._socket.close()

	def _process_command(self, cmd: str) -> str:
		"""
		Executes a command.

		This method expects a command provided as a string and executes it.
		It can instruct the opsipxeconfd to stop, give status information or
		update its BootConfiguration.

		:param cmd: Command to execute. Either 'stop', 'status' or 'update'.
		:type cmd: str
		:returns: Status string depending on the command.
		:rtype: str
		"""
		try:
			try:
				command, args = cmd.split(None, 1)
				arguments = shlex_split(args)
			except ValueError:
				command = cmd.split()[0]

			command = command.strip()

			if command == "stop":
				self._opsipxeconfd.stop()
				return "opsipxeconfd is going down"
			if command == "status":
				return self._opsipxeconfd.status()
			if command == "update":
				if len(arguments) < 1:
					raise ValueError("bad arguments for command 'update', needs <hostId>")
				return self._opsipxeconfd.update_boot_configuration(forceHostId(arguments[0]))

			if command == "remove":
				if len(arguments) < 1:
					raise ValueError("bad arguments for command 'remove', needs <hostId>")
				return self._opsipxeconfd.remove_boot_configuration(forceHostId(arguments[0]))

			raise ValueError(f"Command '{cmd}' not supported")
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Processing command '%s' failed: %s", cmd, err)
			return f"{ERROR_MARKER}: {err}"
