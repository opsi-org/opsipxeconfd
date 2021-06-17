# -*- coding: utf-8 -*-
"""
:copyright: uib GmbH <info@uib.de>
This file is part of opsi - https://www.opsi.org

:license: GNU Affero General Public License version 3
See LICENSES/README.md for more Information
"""

import sys
from opsicommon.logging import logger
from .opsipxeconfdinit import OpsipxeconfdInit

def main() -> None:
	"""
	Main method.

	This method controls the execution flow of the opsipxeconfd.
	"""
	try:
		OpsipxeconfdInit()
	except SystemExit:
		pass
	except Exception as err:
		logger.error(err, exc_info=True)
		print(f"ERROR: {err}", file=sys.stderr)
		sys.exit(1)


if __name__ == '__main__':
	main()
