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

def test_OpsipxeconfdInit():
	#opts = argparse.Namespace(help=None, version=None, command="start", conffile=None, logLevel=7, nofork=None, setup=None)
	#OpsipxeconfdInit(opts)
	#time.sleep(12)
	opts = argparse.Namespace(help=None, version=None, command="status", conffile=None, logLevel=7, nofork=None, setup=None)
	OpsipxeconfdInit(opts)
	time.sleep(3)
	opts = argparse.Namespace(help=None, version=None, command="stop", conffile=None, logLevel=7, nofork=None, setup=None)
	OpsipxeconfdInit(opts)