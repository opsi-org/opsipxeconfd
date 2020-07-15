# -*- coding: utf-8 -*-
"""
:copyright: uib GmbH <info@uib.de>
This file is part of opsi - https://www.opsi.org

:license: GNU Affero General Public License version 3
"""
import argparse

from opsipxeconfd.opsipxeconfd import OpsipxeconfdInit

def test_OpsipxeconfdInit():
	opts = argparse.Namespace(help=None, version=True, start=True)
	init = OpsipxeconfdInit(opts)
