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
	parser.add_argument('--version', '-v', help="Show version information and exit.")
	parser.add_argument('--help', action="store_true", help="Display help.")
	parser.add_argument(
		'--log-level', '--loglevel', '-l', default=LOG_WARNING,
		dest="logLevel", type=int, choices=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
		help="Set the desired loglevel."
	)
	parser.add_argument('start', help="Start main process.")
	parser.add_argument('stop', help="Stop main process.")
	parser.add_argument('status', help="Print status information of the main process.")
	parser.add_argument('update', help="Update PXE boot configuration for client.")

	parser.add_argument('--no-fork', '-F', dest="nofork", help="Do not fork to background.")
	parser.add_argument('--conffile', '-c', help="Location of config file.")

	opts = parser.parse_args()

	if opts.version:
		print(f"{__version__} [python-opsi={python_opsi_version}]")
		sys.exit(0)

	if opts.help:
		parser.print_help()
		sys.exit(0)

	if not (opts.start or opts.stop or opts.status or opts.update):
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
