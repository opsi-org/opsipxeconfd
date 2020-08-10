import time
import threading
import os
import socket
from typing import Callable
from contextlib import contextmanager, closing
from shlex import split as shlex_split

from OPSI.System.Posix import execute, which
from OPSI.Backend.OpsiPXEConfd import ERROR_MARKER
from OPSI.Types import forceFilename, forceHostId, forceUnicode
from opsicommon.logging import logger

@contextmanager
def temporaryPidFile(filepath : str) -> None:
	"""
	Maintain temporary PID file.

	Create a file containing the current pid for 'opsipxeconfd' at `filepath`.
	Leaving the context will remove the file.

	:param filepath: Path of the PID file to create.
	:type filepath: str
	"""
	pidFile = filepath

	logger.debug("Reading old pidFile %r...", pidFile)
	try:
		with open(pidFile, 'r') as pf:
			oldPid = pf.readline().strip()

		if oldPid:
			running = False
			try:
				pids = execute("%s -x opsipxeconfd" % which("pidof"))[0].strip().split()
				for runningPid in pids:
					if runningPid == oldPid:
						running = True
						break
			except Exception as error:
				logger.error(error)

			if running:
				raise Exception(u"Another opsipxeconfd process is running (pid: %s), stop process first or change pidfile." % oldPid)
	except IOError as ioerr:
		if ioerr.errno != 2:  # errno 2 == no such file
			raise ioerr

	logger.info(u"Creating pid file %r", pidFile)
	pid = os.getpid()
	with open(pidFile, "w") as pf:
		pf.write(str(pid))

	try:
		yield
	finally:
		try:
			logger.debug("Removing pid file %r...")
			os.unlink(pidFile)
			logger.info("Removed pid file %r", pidFile)
		except OSError as oserr:
			if oserr.errno != 2:
				logger.error("Failed to remove pid file %r: %s", pidFile, oserr)
		except Exception as error:
			logger.error("Failed to remove pid file %r: %s", pidFile, error)

class StartupTask(threading.Thread):
	"""
	class StartupTask

	This class retrieves the initial boot configuration for the clients.
	"""
	def __init__(self, opsipxeconfd) -> None:
		"""
		StartupTask constructor.

		This constructor initializes a new StartupTask instance.
		The associated opsipxeconfd instance is stored.

		:param opsipxeconfd: Opsipxeconfd this StartupTask instance is issued by.
		:type opsipxeconfd: Opsipxeconfd
		"""
		threading.Thread.__init__(self)
		self._opsipxeconfd = opsipxeconfd
		self._running = False
		self._stop = False

	def run(self) -> None:
		"""
		Main method of StartupTask thread.

		This method collects clientIds for which NetbootProducts exist with a
		related action request. For these clientIds the BootConfiguration of
		the opsipxeconfd is updated.
		"""
		self._running = True
		logger.notice(u"Start setting initial boot configurations")
		try:
			clientIds = [clientToDepot['clientId'] for clientToDepot in
						self._opsipxeconfd._backend.configState_getClientToDepotserver(depotIds=[self._opsipxeconfd.config['depotId']])]

			if clientIds:
				productOnClients = self._opsipxeconfd._backend.productOnClient_getObjects(
					productType=u'NetbootProduct',
					clientId=clientIds,
					actionRequest=['setup', 'uninstall', 'update', 'always', 'once', 'custom']
				)

				clientIds = set()
				for poc in productOnClients:
					clientIds.add(poc.clientId)

				for clientId in clientIds:
					if self._stop:
						return

					try:
						self._opsipxeconfd.updateBootConfiguration(clientId)
					except Exception as error:
						logger.error(u"Failed to update PXE boot config for client '%s': %s", clientId, error)

			logger.notice(u"Finished setting initial boot configurations")
		except Exception as error:
			logger.logException(error)
		finally:
			self._running = False

	def stop(self):
		"""
		StartupTask thread stop method.

		This method requests thread termination.
		"""
		self._stop = True


class ClientConnection(threading.Thread):
	"""
	class ClientConnection

	This class handles a connection between opsipxeconfd and a single client.
	Communication is established via sockets. A callback can be registered
	to trigger an additional action.
	"""
	def __init__(self, opsipxeconfd, connectionSocket : socket, callback : Callable=None) -> None:
		"""
		ClientConnection Constructor.

		This constructor initializes a new ClientConnection instance.
		A reference to the issuing opsipxeconfd is stored. Additionally the
		connectionSocket for the communication is given and stored.
		Optionally a callback can be provided.
		The time of instance creation is stored.

		:param opsipxeconfd: Opsipxeconfd this StartupTask instance is issued by.
		:type opsipxeconfd: Opsipxeconfd
		:param connectionSocket: Socket for communication.
		:type connectionSocket: socket
		:param callback: callback method to be called after command execution.
		:type callback: Callable
		"""
		threading.Thread.__init__(self)
		self._opsipxeconfd = opsipxeconfd
		self._socket = connectionSocket
		self._callback = callback
		self._running = False
		self.startTime = time.time()

	def run(self):
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
				cmd = self._socket.recv(4096)
				cmd = forceUnicode(cmd.strip())
				logger.info(u"Got command '%s'", cmd)

				result = self._processCommand(cmd)
				logger.info(u"Returning result '%s'", result)

				try:
					self._socket.send(result.encode('utf-8'))
				except Exception as error:
					logger.warning("Sending result over socket failed: '%s'", error)
			finally:
				if self._running and self._callback:
					self._callback(self)

	def stop(self):
		"""
		ClientConnection thread stop method.

		This method requests thread termination. The socket is closed.
		"""
		self._running = False
		try:
			self._socket.close()
		except AttributeError:
			pass  # Probably none

	def _processCommand(self, cmd : str) -> str:
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
				command, arguments = cmd.split(None, 1)
				arguments = shlex_split(arguments)
			except ValueError:
				command = cmd.split()[0]

			command = command.strip()

			if command == u'stop':
				self._opsipxeconfd.stop()
				return u'opsipxeconfd is going down'
			elif command == u'status':
				return self._opsipxeconfd.status()
			elif command == u'update':
				if len(arguments) == 2:
					# We have an update path
					hostId = forceHostId(arguments[0])
					cacheFilePath = forceFilename(arguments[1])
					return self._opsipxeconfd.updateBootConfiguration(hostId, cacheFilePath)
				elif len(arguments) == 1:
					hostId = forceHostId(arguments[0])
					return self._opsipxeconfd.updateBootConfiguration(hostId)
				else:
					raise ValueError(u"bad arguments for command 'update', needs <hostId>")

			raise ValueError(u"Command '%s' not supported" % cmd)
		except Exception as error:
			logger.error("Processing command '%s' failed: %s", cmd, error)
			return u'%s: %s' % (ERROR_MARKER, error)
