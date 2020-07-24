# -*- coding: utf-8 -*-
"""
:copyright: uib GmbH <info@uib.de>
This file is part of opsi - https://www.opsi.org

:license: GNU Affero General Public License version 3
See LICENSES/README.md for more Information
"""

import sys
import argparse

from OPSI import __version__ as python_opsi_version
from .opsipxeconfd import OpsipxeconfdInit
from opsicommon.logging import logger, LOG_WARNING
from . import __version__

def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Runs and controls opsipxeconfd.",
		add_help=False
	)
	parser.add_argument('--version', '-v', help="Show version information and exit.", action="store_true")
	parser.add_argument('--help', action="store_true", help="Display help.")
	parser.add_argument('--log-level', '--loglevel', '-l', default=LOG_WARNING,
		dest="logLevel", type=int, choices=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
		help="Set the desired loglevel."
	)

	parser.add_argument('--no-fork', '-F', dest="nofork", help="Do not fork to background.", action='store_true')
	parser.add_argument('--conffile', '-c', help="Location of config file.")
	parser.add_argument('--setup', action="store_true", help="Set up the environment and exit.")
	parser.add_argument('command', metavar='<command>', type=str, nargs='?',
                    help='command - one of: start, stop, status, update')

	opts = parser.parse_args()

	if opts.version:
		print(f"{__version__} [python-opsi={python_opsi_version}]")
		sys.exit(0)

	if opts.help:
		parser.print_help()
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
