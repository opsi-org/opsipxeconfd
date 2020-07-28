# -*- coding: utf-8 -*-
"""
:copyright: uib GmbH <info@uib.de>
This file is part of opsi - https://www.opsi.org

:license: GNU Affero General Public License version 3
"""
import argparse
import time
import os
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

def test_setup():
	opts = argparse.Namespace(**vars(default_opts))
	opts.setup = True
	opts.command = None
	OpsipxeconfdInit(opts)

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
def test_pxeconfigwriter():
	hostId = forceHostId(getfqdn())
	productOnClients = None
	#host = cachedData["host"]
	depotId = forceHostId(getfqdn())

#	newProductOnClients = []
#	productOnClients = self._backend.productOnClient_getObjects(
#		productType=u'NetbootProduct',
#		clientId=hostId,
#		actionRequest=['setup', 'uninstall', 'update', 'always', 'once', 'custom']
#	)
#	for poc in productOnClients:
#		try:
#			productOnDepot = cachedData["productOnDepot"]
#		except KeyError:
#			logger.debug("Searching for product '%s' on depot '%s'", poc.productId, depotId)
#			productOnDepot = self._backend.productOnDepot_getObjects(
#				productType=u'NetbootProduct',
#				productId=poc.productId,
#				depotId=depotId
#			)
#
#			try:
#				productOnDepot = productOnDepot[0]
#			except IndexError:
#				logger.info(u"Product %s not available on depot '%s'", poc.productId, depotId)
#				continue
#
#		if productOnDepot:
#			poc.productVersion = productOnDepot.productVersion
#			poc.packageVersion = productOnDepot.packageVersion
#			newProductOnClients.append(poc)
#
#	productOnClients = newProductOnClients

	#product = cachedData["product"]
	#elilo = cachedData['elilo'] or ''
	#product = None
	#elilo = None
	#pxeConfigTemplate, product = self._getPxeConfigTemplate(hostId, productOnClients, product, elilo)
	pxeConfigTemplate = 'tests/test_data/install-x64'

	pxefile = '/etc/opsi/opsipxeconfd.conf'
		
	append = {
		'pckey': None,	#host.getOpsiHostKey(),
		'hn': hostId.split('.')[0],
		'dn': u'.'.join(hostId.split('.')[1:]),
		'product': None,
		'service': None
	}

#	productPropertyStates = cachedData["productPropertyStates"]
	productPropertyStates = {}
	#backendInfo = cachedData["backendInfo"]
#	backendInfo = self._backend.backend_info()
#	backendInfo['hostCount'] = len(self._backend.host_getIdents(type='OpsiClient'))

	pcw = PXEConfigWriter(pxeConfigTemplate, hostId, productOnClients, append, productPropertyStates, pxefile)
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
	assert " ".join("kernel", PXE_TEMPLATE_FILE) in content