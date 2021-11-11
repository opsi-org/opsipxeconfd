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
from opsipxeconfd.util import temporaryPidFile

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
PID_FILE = 'tests/test_data/pidfile.pid'

"""
@contextmanager
@fixture
def run_opsipxeconfd():
	try:
		opts = argparse.Namespace(**vars(default_opts))
		opts.nofork = True

		pid = os.fork()
		if pid > 0:
			# Parent calls init
			print("before starting opsipxeconfd")
			OpsipxeconfdInit(opts)
			print("after starting opsipxeconfd")
			time.sleep(5)
			os.kill(pid, signal.SIGTERM)
			print("after killing opsipxeconfd")
			return
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
		print("after teardown")
"""

def test_pxeconfigwriter():
	hostId = forceHostId(getfqdn())
	productOnClients = None
	depotId = forceHostId(getfqdn())
	pxeConfigTemplate = os.path.join(TEST_DATA, PXE_TEMPLATE_FILE)
	pxefile = CONFFILE
	append = {
		'pckey': None,	#host.getOpsiHostKey(),
		'hn': hostId.split('.')[0],
		'dn': '.'.join(hostId.split('.')[1:]),
		'product': None,
		'service': None
	}
	productPropertyStates = {}
	pcw = PXEConfigWriter(
		pxeConfigTemplate, hostId, productOnClients, append, productPropertyStates, pxefile, True, True
	)
	content = pcw._getPXEConfigContent(pxeConfigTemplate)
	"""
	default opsi-install-x64
	label opsi-install-x64
	kernel install-x64
	append initrd=miniroot-x64.bz2 video=vesa:ywrap,mtrr vga=791 quiet splash --no-log console=tty1 console=ttyS0 hn=test dn=uib.gmbh product service
	"""
	assert " ".join(["kernel", PXE_TEMPLATE_FILE]) in content

def test_temporarypidfile():
	if os.path.exists(PID_FILE):
		os.remove(PID_FILE)
	with temporaryPidFile(PID_FILE):
		with open(PID_FILE) as filehandle:
			pid = filehandle.readline().strip()
		assert not pid == ""
	assert not os.path.exists(PID_FILE)