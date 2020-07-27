# -*- coding: utf-8 -*-
"""
:copyright: uib GmbH <info@uib.de>
This file is part of opsi - https://www.opsi.org

:license: GNU Affero General Public License version 3
"""
import argparse
import time
from opsicommon.logging import LOG_WARNING
from opsipxeconfd.opsipxeconfd import OpsipxeconfdInit

default_opts = argparse.Namespace(	help=None,
									version=None,
									nofork=None,
									conffile=None,
									setup=None,
									command="start",
									logLevel=7,
									logFile="/var/log/opsi/opsipxeconfd.log",
									maxLogSize=5.0,
									keepRotatedLogs=1,
									logLevelFile=4,
									logLevelStderr=7,
									logFilter=None
)

def test_OpsipxeconfdInit():
	#opts = argparse.Namespace(help=None, version=None, command="start", conffile=None, logLevel=7, nofork=None, setup=None)
	#OpsipxeconfdInit(opts)
	#time.sleep(12)
	opts = argparse.Namespace(**vars(default_opts))
	opts.command = "status"
	OpsipxeconfdInit(opts)
	time.sleep(3)
	opts = argparse.Namespace(**vars(default_opts))
	opts.command = "stop"
	OpsipxeconfdInit(opts)