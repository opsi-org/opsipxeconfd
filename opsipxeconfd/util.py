# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

from __future__ import annotations

import os
import time
from contextlib import closing, contextmanager
from pathlib import Path
from shlex import split as shlex_split
from socket import socket
from threading import Thread
from typing import TYPE_CHECKING, Callable, Generator

import psutil
from opsi.logging import get_logger
from opsi.opsi.service.model.type import to_host_id, to_string

from opsipxeconfd import ERROR_MARKER, get_depot_id

if TYPE_CHECKING:
	from opsipxeconfd.opsipxeconfd import Opsipxeconfd


def ensure_not_already_running(process_name: str | None = None) -> None:
	container_procs = ("containerd-shim", "lxc-start")
	our_pid = os.getpid()
	other_pid = None
	try:
		our_proc = psutil.Process(our_pid)
		if not process_name:
			process_name = our_proc.name()
		exe_name = f"{process_name}.exe"
		ignore_pids = [p.pid for p in our_proc.children(recursive=True)]
		ignore_pids += [p.pid for p in our_proc.parents()]
		for proc in psutil.process_iter():
			# logger.debug("Found running process: %s", proc)
			if proc.name() == process_name or proc.name() == exe_name:
				logger.debug("Found running '%s' process: %s", process_name, proc)

				running_in_container_pid = 0
				for parent in proc.parents():
					if parent.name() in container_procs:
						running_in_container_pid = parent.pid
						break
				if running_in_container_pid:
					logger.debug("Process is running in container %d, skipping", running_in_container_pid)
					continue

				if proc.pid != our_pid and proc.pid not in ignore_pids:
					other_pid = proc.pid
					break
	except Exception as err:
		logger.debug("Check for running processes failed: %s", err)

	if other_pid:
		raise RuntimeError(f"Another '{process_name}' process is running (pids: {other_pid} / {our_pid}).")

	if other_pid:
		raise RuntimeError(f"Another '{process_name}' process is running (pids: {other_pid} / {our_pid}).")


logger = get_logger()


@contextmanager
def pid_file(pid_file_path: str | Path) -> Generator[None, None, None]:
	"""
	Maintain temporary PID file.

	Create a file containing the current pid for 'opsipxeconfd' at `pid_file_path`.
	Leaving the context will remove the file.

	:param pid_file_path: Path of the PID file to create.
	:type pid_file_path: str
	"""
	ensure_not_already_running("opsipxeconfd")

	if not isinstance(pid_file_path, Path):
		pid_file_path = Path(pid_file_path)

	logger.info("Creating pid file '%s'", pid_file_path)
	pid_file_path.write_text(str(os.getpid()), encoding="utf-8")

	try:
		yield
	finally:
		if pid_file_path.exists():
			try:
				logger.debug("Removing pid file '%s'", pid_file_path)
				pid_file_path.unlink()
				logger.info("Removed pid file '%s'", pid_file_path)
			except Exception as err:
				logger.error("Failed to remove pid file '%s': %s", pid_file_path, err)


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
					{"depotIds": [get_depot_id()]},
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

					try:
						self._opsipxeconfd.update_boot_configuration(client_id)
					except Exception as err:
						logger.error("Failed to update PXE boot config for client '%s': %s", client_id, err)

			logger.notice("Finished setting initial boot configurations")
		except Exception as err:
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
				cmd = to_string(self._socket.recv(4096))
				logger.info("Got command '%s'", cmd)

				result = self._process_command(cmd)
				logger.info("Returning result '%s'", result)

				try:
					self._socket.send(result.encode("utf-8"))
				except Exception as err:
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
				return self._opsipxeconfd.update_boot_configuration(to_host_id(arguments[0]))
			if command == "remove":
				if len(arguments) < 1:
					raise ValueError("bad arguments for command 'remove', needs <hostId>")
				return self._opsipxeconfd.remove_boot_configuration(to_host_id(arguments[0]))

			raise ValueError(f"Command '{cmd}' not supported")
		except Exception as err:
			logger.error("Processing command '%s' failed: %s", cmd, err)
			return f"{ERROR_MARKER}: {err}"
			return f"{ERROR_MARKER}: {err}"
