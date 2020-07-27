# -*- coding: utf-8 -*-
"""
:copyright: uib GmbH <info@uib.de>
This file is part of opsi - https://www.opsi.org

:license: GNU Affero General Public License version 3
See LICENSES/README.md for more Information
"""

import sys
import configargparse
import argparse

from OPSI import __version__ as python_opsi_version
from .opsipxeconfd import OpsipxeconfdInit
from opsicommon.logging import logger
from . import __version__

def parse_args() -> argparse.Namespace:
	parser = configargparse.ArgParser(
			formatter_class=lambda prog: argparse.ArgumentDefaultsHelpFormatter(
			prog, max_help_position=30, width=100
		)
	)
	parser.add('--version', '-v', help="Show version information and exit.", action="store_true")
	parser.add('--no-fork', '-F', dest="nofork", help="Do not fork to background.", action='store_true')
	parser.add('--conffile', '-c', help="Location of config file.")
	parser.add('--setup', action="store_true", help="Set up the environment and exit.")
	parser.add('command', metavar='<command>', type=str, nargs='?',
                    help='command - one of: start, stop, status, update')

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


	opts = parser.parse_args()

	if opts.version:
		print(f"{__version__} [python-opsi={python_opsi_version}]")
		sys.exit(0)

	has_command = (opts.command and (opts.command in ["start", "stop", "update", "status"]))

	if not opts.setup and not has_command:
		parser.print_help()
		sys.exit(1)

	return opts
		
def main():
	opts = parse_args()
	try:
		OpsipxeconfdInit(opts)
	except SystemExit:
		pass
	except Exception as exception:
		logger.logException(exception)
		print(u"ERROR: %s" % exception, file=sys.stderr)
		sys.exit(1)


if __name__ == '__main__':
	main()
