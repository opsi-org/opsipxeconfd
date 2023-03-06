# -*- coding: utf-8 -*-

# opsipxeconfd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2013-2023 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

"""
opsipxeconfd - init
"""

import codecs
import os
import sys
import threading
from argparse import ArgumentDefaultsHelpFormatter, Namespace
from collections import OrderedDict
from contextlib import closing, contextmanager
from io import StringIO
from signal import SIGHUP, SIGINT, SIGTERM, signal
from socket import AF_UNIX, SOCK_STREAM, socket
from time import sleep
from types import FrameType
from typing import Any, Generator

from configargparse import (  # type: ignore[import]
	ArgParser,
	ConfigFileParser,
	ConfigFileParserException,
)
from opsicommon import __version__ as python_opsi_common_version
from opsicommon.logging import (
	DEFAULT_FORMAT,
	LOG_WARNING,
	get_logger,
	log_context,
	set_filter_from_string,
)
from opsicommon.types import forceInt, forceUnicode, forceUnicodeList

from . import __version__
from .logging import init_logging
from .opsipxeconfd import Opsipxeconfd, opsi_config
from .setup import setup
from .util import pid_file

DEFAULT_CONFIG_FILE = "/etc/opsi/opsipxeconfd.conf"
ERROR_MARKER = "(ERROR)"


logger = get_logger()


@contextmanager
def create_unix_socket(port: str, timeout: float = 5.0) -> Generator[socket, None, None]:
	logger.notice("Creating unix socket %s", port)
	_socket = socket(AF_UNIX, SOCK_STREAM)
	_socket.settimeout(timeout)
	try:
		with closing(_socket) as unix_socket:
			unix_socket.connect(port)
			yield unix_socket
	except Exception as err:
		raise RuntimeError(f"Failed to connect to socket '{port}': {err}") from err


class ServerConnection:  # pylint: disable=too-few-public-methods
	def __init__(self, port: str, timeout: float = 10.0) -> None:
		self.port = port
		self.timeout = forceInt(timeout)

	def send_command(self, cmd: str) -> str:
		with create_unix_socket(self.port, timeout=self.timeout) as unix_socket:
			unix_socket.send(forceUnicode(cmd).encode("utf-8"))
			result = ""
			try:
				for part in iter(lambda: unix_socket.recv(4096), b""):
					logger.trace("Received %s", part)
					result += forceUnicode(part)
			except Exception as err:  # pylint: disable=broad-except
				raise RuntimeError(f"Failed to receive: {err}") from err

		if result.startswith(ERROR_MARKER):
			raise RuntimeError(f"Command '{cmd}' failed: {result}")

		return result


class OpsipxeconfdConfigFileParser(ConfigFileParser):  # pylint: disable=abstract-method
	def get_syntax_description(self) -> str:
		return ""

	def parse(self, stream: StringIO) -> dict[str, Any]:  # pylint: disable=too-many-branches
		items = OrderedDict()
		for i, line in enumerate(stream):
			line = line.strip()
			if not line or line.startswith(("#", ";", "/")):
				continue
			if "=" not in line:
				raise ConfigFileParserException(f"Unexpected line {i} in {getattr(stream, 'name', 'stream')}: {line}")

			(option, value) = line.split("=", 1)
			option = option.strip()
			value = value.strip()
			if option == "pid file":
				items["pid-file"] = value
			elif option == "log level":
				items["log-level"] = value
			elif option == "log level stderr":
				items["log-level-stderr"] = value
			elif option == "log level file":
				items["log-level-file"] = value
			elif option == "max byte log":
				items["max-log-size"] = value
			elif option == "backup count log":
				items["keep-rotated-logs"] = value
			elif option == "log file":
				items["log-file"] = value
			elif option == "log format":
				# Ignore
				pass
			elif option == "pxe config dir":
				items["pxe-dir"] = value
			elif option == "pxe config template":
				items["pxe-conf-template"] = value
			elif option == "max pxe config writers":
				items["max-pxe-config-writers"] = value
			elif option == "max control connections":
				items["max-connections"] = value
			elif option == "backend config dir":
				items["backend-config-dir"] = value
			elif option == "dispatch config file":
				items["dispatch-config-file"] = value
			else:
				raise ConfigFileParserException(f"Unexpected option in line {i} in {getattr(stream, 'name', 'stream')}: {option}")
		return items


def parse_args() -> Namespace:
	"""
	Parses command line arguments.

	This method takes command line arguments provided as sys.argv and parses them
	to extract keywords and values to set for certain variables.

	:returns: Namespace object containing all provided settings (or defaults).
	:rtype: Namespace
	"""
	parser = ArgParser(
		config_file_parser_class=OpsipxeconfdConfigFileParser,
		formatter_class=lambda prog: ArgumentDefaultsHelpFormatter(prog, max_help_position=30, width=100),
	)
	parser.add("--version", "-v", help="Show version information and exit.", action="store_true")
	parser.add("--no-fork", "-F", dest="nofork", help="Do not fork to background.", action="store_true")
	parser.add("-c", "--conffile", required=False, is_config_file=True, default=DEFAULT_CONFIG_FILE, help="Path to config file.")
	parser.add("--setup", action="store_true", help="Set up the environment and exit.")
	parser.add(
		"--log-level",
		"--loglevel",
		"--l",
		env_var="OPSIPXECONFD_LOG_LEVEL",
		type=int,
		default=5,
		choices=range(0, 10),
		dest="logLevel",
		help="Set the general log level."
		+ "0: nothing, 1: essential, 2: critical, 3: errors, 4: warnings, 5: notices"
		+ " 6: infos, 7: debug messages, 8: trace messages, 9: secrets",
	)
	parser.add(
		"--log-file",
		env_var="OPSIPXECONFD_LOG_FILE",
		default="/var/log/opsi/opsipxeconfd/opsipxeconfd.log",
		dest="logFile",
		help="Log file to use.",
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
		+ "so that your disk does not get filled by the logs.",
	)
	parser.add(
		"--keep-rotated-logs",
		env_var="OPSIPXECONFD_KEEP_ROTATED_LOGS",
		type=int,
		default=1,
		dest="keepRotatedLogs",
		help="Number of rotated log files to keep.",
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
		+ " 6: infos, 7: debug messages, 8: trace messages, 9: secrets",
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
		+ " 6: infos, 7: debug messages, 8: trace messages, 9: secrets",
	)
	parser.add(
		"--log-filter",
		env_var="OPSIPXECONFD_LOG_FILTER",
		dest="logFilter",
		help="Filter log records contexts (<ctx-name-1>=<val1>[,val2][;ctx-name-2=val3])",
	)
	parser.add(
		"--backend-config-dir",
		dest="backendConfigDir",
		env_var="OPSIPXECONFD_BACKEND_CONFIG_DIR",
		default="/etc/opsi/backends",
		help="Location of the backend config dir.",
	)
	parser.add(
		"--dispatch-config-file",
		dest="dispatchConfigFile",
		env_var="OPSIPXECONFD_DISPATCH_CONFIG_FILE",
		default="/etc/opsi/backendManager/dispatch.conf",
		help="Location of the backend dispatcher config file.",
	)
	parser.add(
		"--pid-file",
		dest="pidFile",
		env_var="OPSIPXECONFD_PID_FILE",
		default="/var/run/opsipxeconfd/opsipxeconfd.pid",
		help="Location of the pid file.",
	)
	parser.add(
		"--pxe-dir",
		dest="pxeDir",
		env_var="OPSIPXECONFD_PXE_DIR",
		default="/tftpboot/linux/pxelinux.cfg",
		help="Location of the pxe directory.",
	)
	parser.add(
		"--pxe-conf-template",
		dest="pxeConfTemplate",
		env_var="OPSIPXECONFD_PXE_CONF_TEMPLATE",
		default="/tftpboot/linux/pxelinux.cfg/install",
		help="Location of the pxe config template.",
	)
	parser.add(
		"--max-connections",
		env_var="OPSIPXECONFD_MAX_CONNECTIONS",
		type=int,
		default=5,
		dest="maxConnections",
		help="Number of maximum simultaneous control connections.",
	)
	parser.add(
		"--max-pxe-config-writers",
		env_var="OPSIPXECONFD_MAX_PXE_CONFIG_WRITERS",
		type=int,
		default=100,
		dest="maxPxeConfigWriters",
		help="Number of maximum simultaneous pxe config writer threads.",
	)
	parser.add(
		"command",
		nargs="?",
		choices=("start", "stop", "status", "update"),
		metavar="<command>",
	)
	parser.add(
		"--uefi-conf-template-x86",
		dest="uefiConfTemplateX86",
		env_var="OPSIPXECONFD_UEFI_CONF_TEMPLATE_X86",
		default="/tftpboot/linux/pxelinux.cfg/install-elilo-x86",
		help="(Deprecated) Location of the uefi x86 config template.",
	)
	parser.add(
		"--uefi-conf-template-x64",
		dest="uefiConfTemplateX64",
		env_var="OPSIPXECONFD_UEFI_CONF_TEMPLATE_X64",
		default="/tftpboot/linux/pxelinux.cfg/install-grub-x64",
		help="(Deprecated) Location of the uefi x64 config template.",
	)

	opts = parser.parse_args()

	if opts.version:
		print(f"{__version__} [python-opsi-common={python_opsi_common_version}]")
		sys.exit(0)

	has_command = opts.command and (opts.command in ["start", "stop", "update", "status"])

	if not opts.setup and not has_command:
		parser.print_help()
		sys.exit(1)

	return opts


def assemble_command(config: dict[str, Any]) -> list[str]:
	command = [config["command"]]
	if config.get("nofork"):
		command.append("--no-fork")
	command.append(f"--log-level-stderr={config['logLevelStderr']}")
	command.append(f"--log-level-file={config['logLevelFile']}")
	command.append(f"--logLevel={config['logLevel']}")

	if config.get("conffile") is not None:
		command.append(f"--conffile={config['conffile']}")
	# Theoretically it is possible for the user to specify additional commands, not captured here.
	return command


class OpsipxeconfdInit:
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
		(previously parsed and converted into an Namespace).
		Depending on the command specified on command line, an action is triggered.
		This could be start, stop, update or status.

		:param opts: Parsed command line arguments as Namespace.
		:type opts: Namespace.
		"""
		self.update_config_file()

		self.config = vars(parse_args())
		self.config["port"] = "/var/run/opsipxeconfd/opsipxeconfd.socket"
		self.config["depotId"] = opsi_config.get("host", "id")
		self.config["daemon"] = True
		if self.config["nofork"] and self.config["command"] == "start":
			self.config["daemon"] = False

		logger.setLevel(LOG_WARNING)
		logger.debug("OpsiPXEConfdInit")
		# Set umask
		os.umask(0o077)
		self._pid = 0

		if self.config.get("logFilter"):
			set_filter_from_string(self.config["logFilter"])
		init_logging(self.config)
		if self.config.get("setup"):
			with log_context({"instance": "Opsipxeconfd setup"}):
				setup(self.config)
			return  # TODO: exit code handling

		if self.config.get("command") == "start":
			# Call signal_handler on signal SIGHUP, SIGTERM, SIGINT
			signal(SIGHUP, self.signal_handler)
			signal(SIGTERM, self.signal_handler)
			signal(SIGINT, self.signal_handler)

			if self.config["daemon"]:
				self.daemonize()
			with log_context({"instance": "Opsipxeconfd start"}):
				with pid_file(self.config["pidFile"]):
					self._opsipxeconfd = Opsipxeconfd(self.config)
					self._opsipxeconfd.start()
					sleep(1)
					while self._opsipxeconfd.is_running():
						sleep(1)
					self._opsipxeconfd.join(30)
					if self._opsipxeconfd.error:
						print(f"ERROR: {self._opsipxeconfd.error}")
						sys.exit(1)
					sys.exit(0)
		else:
			with log_context({"instance": " ".join(["Opsipxeconfd", self.config["command"]])}):
				command = assemble_command(self.config)
				con = ServerConnection(self.config["port"], timeout=5.0)
				result = con.send_command(" ".join(forceUnicodeList(command)))
				print(result)

	def signal_handler(self, signo: int, frame: FrameType | None) -> None:  # pylint: disable=unused-argument
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
				self._opsipxeconfd.set_config(self.config)
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

	def update_config_file(self) -> None:
		"""
		Updates Opsipxeconfd config file.

		This method modifies the data written in the configFile to conform to
		the standard logging format.
		"""
		config_file = DEFAULT_CONFIG_FILE
		if not os.path.exists(config_file):
			return

		lines = []
		changed = False
		with open(config_file, encoding="utf-8") as file:
			for line in file.readlines():
				cur_line = line

				if line.startswith("uefi netboot config template"):
					line = f"#{line}"
				elif line.startswith("pxe config dir"):
					line = line.replace("/tftpboot/linux/pxelinux.cfg", "/tftpboot/opsi/opsi-linux-bootimage/cfg")
				elif line.startswith("pxe config template"):
					line = line.replace("/tftpboot/linux/pxelinux.cfg/install", "/tftpboot/opsi/opsi-linux-bootimage/cfg/install-grub-x64")
				elif line.startswith("log format"):
					line = line.replace("[%l] [%D] %M (%F|%N)", DEFAULT_FORMAT)
					line = line.replace("%D", "%(asctime)s")
					line = line.replace("%T", "%(thread)d")
					line = line.replace("%l", "%(opsilevel)d")
					line = line.replace("%L", "%(levelname)s")
					line = line.replace("%M", "%(message)s")
					line = line.replace("%F", "%(filename)s")
					line = line.replace("%N", "%(lineno)s")

				lines.append(line)
				if not changed and line != cur_line:
					changed = True

		if changed:
			logger.notice("Updating config file: %s", config_file)
			with open(config_file, "w", encoding="utf-8") as file:
				file.writelines(lines)

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
		except OSError as err:
			raise RuntimeError(f"First fork failed: {err}") from err

		# Do not hinder umounts
		os.chdir("/")
		# Create a new session
		os.setsid()

		# Fork a second time to not remain session leader
		try:
			self._pid = os.fork()
			if self._pid > 0:
				sys.exit(0)
		except OSError as err:
			raise RuntimeError(f"Second fork failed: {err}") from err

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
