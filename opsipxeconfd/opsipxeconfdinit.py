#! /usr/bin/python3
# -*- coding: utf-8 -*-
"""
opsi pxe configuration daemon (opsipxeconfd)

opsipxeconfd is part of the desktop management solution opsi
(open pc server integration) http://www.opsi.org

Copyright (C) 2013-2019 uib GmbH

http://www.uib.de/

All rights reserved.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License, version 3
as published by the Free Software Foundation.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
Affero General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

@copyright:	uib GmbH <info@uib.de>
@author: Erol Ueluekmen <e.ueluekmen@uib.de>
@author: Jan Schneider <j.schneider@uib.de>
@author: Niko Wenselowski <n.wenselowski@uib.de>
@license: GNU Affero GPL version 3
"""

import codecs
import os
import sys
import threading
import time
import argparse
from typing import Dict, Any
from contextlib import contextmanager
from signal import SIGHUP, SIGINT, SIGTERM, signal

from .logging import init_logging
from .setup import setup
from .util import temporaryPidFile
from opsicommon.logging import (
	logger, DEFAULT_FORMAT, LOG_NONE,
	LOG_NOTICE, LOG_WARNING, log_context, set_filter_from_string
)

from OPSI.Backend.BackendManager import BackendManager
from OPSI.Backend.OpsiPXEConfd import ServerConnection
from OPSI.Util import getfqdn
from OPSI.Util.File import ConfigFile
from OPSI.Types import (forceHostId, forceInt, forceUnicode, forceUnicodeList, forceFilename)
from .opsipxeconfd import Opsipxeconfd

def assemble_command(config):
	command = [config["command"]]
	if config.nofork:
		command.append("--no-fork")
	command.append(f"--log-level-stderr={config['logLevelStderr']}")
	command.append(f"--log-level-file={config['logLevelFile']}")
	command.append(f"--logLevel={config['logLevel']}")

	if config.conffile is not None:
		command.append(f"--conffile={config['conffile']}")
	# Theoretically it is possible for the user to specify additional commands, not captured here.
	return command

class OpsipxeconfdInit(object):
	"""
	class OpsipxeconfdInit.

	This class sets up all preconditions for an Opsipxeconfd thread.
	Settings are loaded from config files and command line and
	logging is set up. This class also handles command calls which
	are passed to a running instance of Opsipxeconfd.
	"""
	def __init__(self, config : argparse.Namespace) -> None:
		"""
		OpsipxeconfdInit constructor.

		This constructor creates an OpsipxeconfdInit instance. The settings are
		determined by values in the config file and command line arguments
		(previously parsed and converted into an argparse.Namespace).
		Depending on the command specified on command line, an action is triggered.
		This could be start, stop, update or status.

		:param opts: Parsed command line arguments as argparse.Namespace.
		:type opts: argparse.Namespace.
		"""
		self.config = vars(config)
		self.config["port"] = '/var/run/opsipxeconfd/opsipxeconfd.socket'
		self.config["depotId"] = forceHostId(getfqdn())
		self.config["daemon"] = True
		if self.config["nofork"] and self.config["command"] == "start":
			self.config["daemon"] = False

		logger.setLevel(LOG_WARNING)
		logger.debug("OpsiPXEConfdInit")
		# Set umask
		os.umask(0o077)
		self._pid = 0

		self.updateConfigFile()

		if self.config.get("logFilter"):
			set_filter_from_string(self.config["logFilter"])
		init_logging(self.config)
		if self.config.get("setup"):
			with log_context({'instance' : 'Opsipxeconfd setup'}):
				setup(self.config)
			return		#TODO: exit code handling

		if self.config.get("command") == "start":
			# Call signalHandler on signal SIGHUP, SIGTERM, SIGINT
			signal(SIGHUP, self.signalHandler)
			signal(SIGTERM, self.signalHandler)
			signal(SIGINT, self.signalHandler)

			if self.config["daemon"]:
				self.daemonize()
			with log_context({'instance' : 'Opsipxeconfd start'}):
				with temporaryPidFile(self.config['pidFile']):
					self._opsipxeconfd = Opsipxeconfd(self.config)
					self._opsipxeconfd.start()
					time.sleep(3)
					while self._opsipxeconfd.isRunning():
						time.sleep(1)
					self._opsipxeconfd.join(30)
		else:
			with log_context({'instance' : " ".join(['Opsipxeconfd', self.config["command"]])}):
				command = assemble_command(self.config)
				con = ServerConnection(self.config["port"], timeout=5.0)
				result = con.sendCommand(" ".join(forceUnicodeList(command)))

	def signalHandler(self, signo, stackFrame)-> None:
		"""
		Signal Handler for OpsipxeconfdInit.

		This method can be hooked to OS-signals. Depending of the type
		of signal it acts accordingly. For signal SIGHUP it reloads the config
		from file and attempts to reload the Opsipxeconfd. For signal
		SIGTERM and SIGINT the Opsipxeconfd is stopped.

		:param signo: Number of the signal to process.
		:type signo: int
		:param stackFrame: unused
		:type stackFrame: Any
		"""
		for thread in threading.enumerate():
			logger.debug("Running thread before signal: %s", thread)

		logger.debug("Processing signal %r", signo)
		if signo == SIGHUP:
			self.setDefaultConfig()
			try:

				self._opsipxeconfd.setConfig(self.config)
				self._opsipxeconfd.reload()
			except AttributeError:
				pass  # probably set to None
		elif signo in (SIGTERM, SIGINT):
			try:
				self._opsipxeconfd.stop()
			except AttributeError:
				pass  # probably set to None

		for thread in threading.enumerate():
			logger.debug("Running thread after signal: %s", thread)

	def updateConfigFile(self) -> None:
		"""
		Updates Opsipxeconfd config file.

		This method modifies the data written in the configFile to conform to
		the standard logging format.
		"""
		with codecs.open(self.config['conffile'], 'r', "utf-8") as f:
			data = f.read()
		new_data = data.replace("[%l] [%D] %M (%F|%N)", DEFAULT_FORMAT)
		new_data = new_data.replace("%D", "%(asctime)s")
		new_data = new_data.replace("%T", "%(thread)d")
		new_data = new_data.replace("%l", "%(opsilevel)d")
		new_data = new_data.replace("%L", "%(levelname)s")
		new_data = new_data.replace("%M", "%(message)s")
		new_data = new_data.replace("%F", "%(filename)s")
		new_data = new_data.replace("%N", "%(lineno)s")
		if new_data != data:
			logger.notice("Updating config file: %s", self.config['conffile'])
			with codecs.open(self.config['conffile'], 'w', "utf-8") as f:
				f.write(new_data)

	def daemonize(self) -> None:
		"""
		Lets process run as daemon.

		This method forks the current process and closes the parent.
		For the child stdout and stderr data streams are uncoupled.
		"""
		# Fork to allow the shell to return and to call setsid
		try:
			self._pid = os.fork()
			if self._pid > 0:
				# Parent exits
				sys.exit(0)
		except OSError as error:
			raise Exception("First fork failed: %e", error)

		# Do not hinder umounts
		os.chdir("/")
		# Create a new session
		os.setsid()

		# Fork a second time to not remain session leader
		try:
			self._pid = os.fork()
			if self._pid > 0:
				sys.exit(0)
		except OSError as error:
			raise Exception(u"Second fork failed: %e" % error)

		# logger.setConsoleLevel(LOG_NONE)

		# Close standard output and standard error.
		os.close(0)
		os.close(1)
		os.close(2)

		# Open standard input (0)
		if hasattr(os, "devnull"):
			os.open(os.devnull, os.O_RDWR)
		else:
			os.open("/dev/null", os.O_RDWR)

		# Duplicate standard input to standard output and standard error.
		os.dup2(0, 1)
		os.dup2(0, 2)
		# sys.stdout = logger.getStdout()
		# sys.stderr = logger.getStderr()
