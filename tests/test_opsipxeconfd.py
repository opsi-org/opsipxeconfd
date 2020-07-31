# -*- coding: utf-8 -*-
"""
:copyright: uib GmbH <info@uib.de>
This file is part of opsi - https://www.opsi.org

:license: GNU Affero General Public License version 3
"""
import argparse
import time
import os
import signal
from pytest import fixture
from contextlib import contextmanager

from opsicommon.logging import LOG_WARNING
from opsipxeconfd.opsipxeconfdinit import OpsipxeconfdInit
from opsipxeconfd.pxeconfigwriter import PXEConfigWriter

from OPSI.Types import forceHostId
from OPSI.Util import getfqdn

default_opts = argparse.Namespace(	help=False,
									version=False,
									nofork=False,
									conffile=None,
									setup=False,
									command="start",
									logLevel=7,
									logFile="/var/log/opsi/opsipxeconfd.log",
									maxLogSize=5.0,
									keepRotatedLogs=1,
									logLevelFile=4,
									logLevelStderr=7,
									logFilter=None
)

TEST_DATA = 'tests/test_data/'
PXE_TEMPLATE_FILE = 'install-x64'
CONFFILE = '/etc/opsi/opsipxeconfd.conf'

@contextmanager
@fixture
def run_opsipxeconfd():
	try:
		opts = argparse.Namespace(**vars(default_opts))
		opts.nofork = True

		pid = os.fork()
		if pid > 0:
			# Parent calls init
			OpsipxeconfdInit(opts)
			print("after start - should never be printed")
		else:
			# Child yields
			time.sleep(12)
			print("before yield")
			yield
			print("after yield")
	except OSError as error:
		raise Exception("Fork failed: %e", error)
	finally:
		print("before teardown")
		opts = argparse.Namespace(**vars(default_opts))
		opts.command = "stop"
		OpsipxeconfdInit(opts)
		time.sleep(5)
		os.kill(pid, signal.SIGTERM)
		print("after teardown")

def test_setup():
	opts = argparse.Namespace(**vars(default_opts))
	opts.setup = True
	opts.command = None
	OpsipxeconfdInit(opts)

"""
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
"""

def test_OpsipxeconfdInit2(run_opsipxeconfd):
	with run_opsipxeconfd:
		opts = argparse.Namespace(**vars(default_opts))
		opts.command = "status"
		OpsipxeconfdInit(opts)
		time.sleep(5)

def test_pxeconfigwriter():
	hostId = forceHostId(getfqdn())
	productOnClients = None
	depotId = forceHostId(getfqdn())
	pxeConfigTemplate = os.path.join(TEST_DATA, PXE_TEMPLATE_FILE)
	pxefile = CONFFILE
	append = {
		'pckey': None,	#host.getOpsiHostKey(),
		'hn': hostId.split('.')[0],
		'dn': u'.'.join(hostId.split('.')[1:]),
		'product': None,
		'service': None
	}
	productPropertyStates = {}
	pcw = PXEConfigWriter(pxeConfigTemplate, hostId, productOnClients, append, productPropertyStates, pxefile)
	content = pcw._getPXEConfigContent(pxeConfigTemplate)
	"""
	default opsi-install-x64
	label opsi-install-x64
	kernel install-x64
	append initrd=miniroot-x64.bz2 video=vesa:ywrap,mtrr vga=791 quiet splash --no-log console=tty1 console=ttyS0 hn=test dn=uib.gmbh product service
	"""
	assert " ".join(["kernel", PXE_TEMPLATE_FILE]) in content