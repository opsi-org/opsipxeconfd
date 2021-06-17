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
@license: GNU Affero GPL version 3
"""

import codecs
import os
import sys
import threading
import time
import argparse
from signal import SIGHUP, SIGINT, SIGTERM, signal
from collections import OrderedDict
import configargparse
import argparse

from opsicommon.logging import (
	logger, DEFAULT_FORMAT, LOG_WARNING, log_context, set_filter_from_string
)

from OPSI.Backend.OpsiPXEConfd import ServerConnection
from OPSI.Util import getfqdn
from OPSI.Types import (forceHostId, forceUnicodeList)
from OPSI import __version__ as python_opsi_version

from .logging import init_logging
from .setup import setup
from .util import temporaryPidFile
from .opsipxeconfd import Opsipxeconfd
from . import __version__

DEFAULT_CONFIG_FILE = "/etc/opsi/opsipxeconfd.conf"


class OpsipxeconfdConfigFileParser(configargparse.ConfigFileParser):
	def get_syntax_description(self):
		return ""

	def parse(self, stream):
		items = OrderedDict()
		for i, line in enumerate(stream):
			line = line.strip()
			if not line or line.startswith(("#", ";", "/")):
				continue
			if '=' not in line:
				raise configargparse.ConfigFileParserException(
					f"Unexpected line {i} in {getattr(stream, 'name', 'stream')}: {line}"
				)

			(option, value) = line.split('=', 1)
			option = option.strip()
			value = value.strip()
			if option == 'pid file':
				items['pid-file'] = value
			elif option == 'log level':
				items['log-level'] = value
			elif option == 'log level stderr':
				items['log-level-stderr'] = value
			elif option == 'log level file':
				items['log-level-file'] = value
			elif option == 'max byte log':
				items['max-log-size'] = value
			elif option == 'backup count log':
				items['keep-rotated-logs'] = value
			elif option == 'log file':
				items['log-file'] = value
			elif option == 'log format':
				# Ignore
				pass
			elif option == 'pxe config dir':
				items['pxe-dir'] = value
			elif option == 'pxe config template':
				items['pxe-conf-template'] = value
			elif option == 'uefi netboot config template x86':
				items['uefi-conf-template-x86'] = value
			elif option == 'uefi netboot config template x64':
				items['uefi-conf-template-x64'] = value
			elif option == 'max pxe config writers':
				items['max-pxe-config-writers'] = value
			elif option == 'max control connections':
				items['max-connections'] = value
			elif option == 'backend config dir':
				items['backend-config-dir'] = value
			elif option == 'dispatch config file':
				items['dispatch-config-file'] = value
			else:
				raise configargparse.ConfigFileParserException(
					f"Unexpected option in line {i} in {getattr(stream, 'name', 'stream')}: {option}"
				)
		return items

def parse_args() -> argparse.Namespace:
	"""
	Parses command line arguments.

	This method takes command line arguments provided as sys.argv and parses them
	to extract keywords and values to set for certain variables.

	:returns: Namespace object containing all provided settings (or defaults).
	:rtype: argparse.Namespace
	"""
	parser = configargparse.ArgParser(
		config_file_parser_class=OpsipxeconfdConfigFileParser,
		formatter_class=lambda prog: argparse.ArgumentDefaultsHelpFormatter(
			prog, max_help_position=30, width=100
		)
	)
	parser.add('--version', '-v', help="Show version information and exit.", action="store_true")
	parser.add('--no-fork', '-F', dest="nofork", help="Do not fork to background.", action='store_true')
	parser.add(
		"-c", "--conffile",
		required=False,
		is_config_file=True,
		default=DEFAULT_CONFIG_FILE,
		help="Path to config file."
	)
	parser.add('--setup', action="store_true", help="Set up the environment and exit.")
	parser.add(
		"--log-level", "--loglevel", "--l",
		env_var="OPSIPXECONFD_LOG_LEVEL",
		type=int,
		default=5,
		choices=range(0, 10),
		dest="logLevel",
		help="Set the general log level."
			+ "0: nothing, 1: essential, 2: critical, 3: errors, 4: warnings, 5: notices"
			+ " 6: infos, 7: debug messages, 8: trace messages, 9: secrets"
	)
	parser.add(
		"--log-file",
		env_var="OPSIPXECONFD_LOG_FILE",
		default="/var/log/opsi/opsipxeconfd.log",
		dest="logFile",
		help="Log file to use."
	)
	parser.add(
		"--max-log-size",
		env_var="OPSIPXECONFD_MAX_LOG_SIZE",
		type=float,
		default=5.0,
		dest="maxLogSize",
		help="Limit the size of logfiles to SIZE megabytes."
			+ "Setting this to 0 will disable any limiting."
			+ "If you set this to 0 we recommend using a proper logrotate configuration"
			+ "so that your disk does not get filled by the logs."
	)
	parser.add(
		"--keep-rotated-logs",
		env_var="OPSIPXECONFD_KEEP_ROTATED_LOGS",
		type=int,
		default=1,
		dest="keepRotatedLogs",
		help="Number of rotated log files to keep."
	)
	parser.add(
		"--log-level-file",
		env_var="OPSIPXECONFD_LOG_LEVEL_FILE",
		type=int,
		default=4,
		choices=range(0, 10),
		dest="logLevelFile",
		help="Set the log level for logfiles."
			+ "0: nothing, 1: essential, 2: critical, 3: errors, 4: warnings, 5: notices"
			+ " 6: infos, 7: debug messages, 8: trace messages, 9: secrets"
	)
	parser.add(
		"--log-level-stderr",
		env_var="OPSIPXECONFD_LOG_LEVEL_STDERR",
		type=int,
		default=4,
		choices=range(0, 10),
		dest="logLevelStderr",
		help="Set the log level for stderr."
			+ "0: nothing, 1: essential, 2: critical, 3: errors, 4: warnings, 5: notices"
			+ " 6: infos, 7: debug messages, 8: trace messages, 9: secrets"
	)
	parser.add(
		"--log-filter",
		env_var="OPSIPXECONFD_LOG_FILTER",
		dest="logFilter",
		help="Filter log records contexts (<ctx-name-1>=<val1>[,val2][;ctx-name-2=val3])"
	)
	parser.add(
		"--backend-config-dir",
		dest="backendConfigDir",
		env_var="OPSIPXECONFD_BACKEND_CONFIG_DIR",
		default="/etc/opsi/backends",
		help="Location of the backend config dir."
	)
	parser.add(
		"--dispatch-config-file",
		dest="dispatchConfigFile",
		env_var="OPSIPXECONFD_DISPATCH_CONFIG_FILE",
		default="/etc/opsi/backendManager/dispatch.conf",
		help="Location of the backend dispatcher config file."
	)
	parser.add(
		"--pid-file",
		dest="pidFile",
		env_var="OPSIPXECONFD_PID_FILE",
		default="/var/run/opsipxeconfd/opsipxeconfd.pid",
		help="Location of the pid file."
	)
	parser.add(
		"--pxe-dir",
		dest="pxeDir",
		env_var="OPSIPXECONFD_PXE_DIR",
		default="/tftpboot/linux/pxelinux.cfg",
		help="Location of the pxe directory."
	)
	parser.add(
		"--pxe-conf-template",
		dest="pxeConfTemplate",
		env_var="OPSIPXECONFD_PXE_CONF_TEMPLATE",
		default="/tftpboot/linux/pxelinux.cfg/install",
		help="Location of the pxe config template."
	)
	parser.add(
		"--uefi-conf-template-x86",
		dest="uefiConfTemplateX86",
		env_var="OPSIPXECONFD_UEFI_CONF_TEMPLATE_X86",
		default="/tftpboot/linux/pxelinux.cfg/install-elilo-x86",
		help="Location of the uefi x86 config template."
	)
	parser.add(
		"--uefi-conf-template-x64",
		dest="uefiConfTemplateX64",
		env_var="OPSIPXECONFD_UEFI_CONF_TEMPLATE_X64",
		default="/tftpboot/linux/pxelinux.cfg/install-grub-x64",
		help="Location of the uefi x64 config template."
	)
	parser.add(
		"--max-connections",
		env_var="OPSIPXECONFD_MAX_CONNECTIONS",
		type=int,
		default=5,
		dest="maxConnections",
		help="Number of maximum simultaneous control connections."
	)
	parser.add(
		"--max-pxe-config-writers",
		env_var="OPSIPXECONFD_MAX_PXE_CONFIG_WRITERS",
		type=int,
		default=100,
		dest="maxPxeConfigWriters",
		help="Number of maximum simultaneous pxe config writer threads."
	)
	parser.add(
		"command",
		nargs="?",
		choices=("start", "stop", "status", "update"),
		metavar="<command>",
	)

	opts = parser.parse_args()

	if opts.version:
		print(f"{__version__} [python-opsi={python_opsi_version}]")
		sys.exit(0)

	has_command = (opts.command and (opts.command in ["start", "stop", "update", "status"]))

	if not opts.setup and not has_command:
		parser.print_help()
		sys.exit(1)

	return opts


def assemble_command(config):
	command = [config["command"]]
	if config.get("nofork"):
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
	def __init__(self) -> None:
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
		self.config = vars(parse_args())
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
			try:
				self.config.update(vars(parse_args()))
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
			raise Exception("Second fork failed: %e" % error)

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
