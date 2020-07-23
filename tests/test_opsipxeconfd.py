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

CONFFILE = "tests/test_data/opsipxeconfd.conf"

def test_OpsipxeconfdInit():
	opts = argparse.Namespace(help=None, version=None, command="start", conffile=CONFFILE, logLevel=LOG_WARNING, nofork=True)
	OpsipxeconfdInit(opts)
	time.sleep(8)
	opts = argparse.Namespace(help=None, version=None, command="status", conffile=CONFFILE, logLevel=LOG_WARNING, nofork=True)
	OpsipxeconfdInit(opts)
	time.sleep(2)
	opts = argparse.Namespace(help=None, version=None, command="status", conffile=CONFFILE, logLevel=LOG_WARNING, nofork=True)
	OpsipxeconfdInit(opts)