# -*- coding: utf-8 -*-
"""
:copyright: uib GmbH <info@uib.de>
This file is part of opsi - https://www.opsi.org

:license: GNU Affero General Public License version 3
See LICENSES/README.md for more Information
"""

import sys
from collections import OrderedDict
import configargparse
import argparse

from OPSI import __version__ as python_opsi_version
from opsicommon.logging import logger

from .opsipxeconfdinit import OpsipxeconfdInit
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

def main() -> None:
	"""
	Main method.

	This method controls the execution flow of the opsipxeconfd.
	"""
	opts = parse_args()
	try:
		OpsipxeconfdInit(opts)
	except SystemExit:
		pass
	except Exception as err:
		logger.error(err, exc_info=True)
		print(f"ERROR: {err}", file=sys.stderr)
		sys.exit(1)


if __name__ == '__main__':
	main()
