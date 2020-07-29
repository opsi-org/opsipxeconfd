#! /usr/bin/python3
# -*- coding: utf-8 -*-
"""
opsi pxe configuration daemon (opsipxeconfd)

opsipxeconfd is part of the desktop management solution opsi
(open pc server integration) http://www.opsi.org

Copyright (C) 2013-2019 uib GmbH

http://www.uib.de/

All rights reserved.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License, version 3
as published by the Free Software Foundation.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
Affero General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

@copyright:	uib GmbH <info@uib.de>
@author: Erol Ueluekmen <e.ueluekmen@uib.de>
@author: Jan Schneider <j.schneider@uib.de>
@author: Niko Wenselowski <n.wenselowski@uib.de>
@license: GNU Affero GPL version 3
"""

import codecs
import json
import grp
import os
import socket
import stat
import threading
import time

from .logging import init_logging
from .util import StartupTask, ClientConnection
from opsicommon.logging import logger, log_context

from OPSI.Backend.BackendManager import BackendManager
from OPSI.Config import OPSI_ADMIN_GROUP
from OPSI.Exceptions import BackendMissingDataError
from OPSI.Util import deserialize
from OPSI.Util.File import ConfigFile
from OPSI.Types import forceFilename, forceHostId, forceUnicode, forceUnicodeList

from .pxeconfigwriter import PXEConfigWriter

ELILO_X86 = 'x86'
ELILO_X64 = 'x64'

class Opsipxeconfd(threading.Thread):
	def __init__(self, config):
		threading.Thread.__init__(self)

		self.config = config
		self._running = False

		self._backend = None
		self._socket = None
		self._clientConnectionLock = threading.Lock()
		self._pxeConfigWritersLock = threading.Lock()
		self._clientConnections = []
		self._pxeConfigWriters = []
		self._startupTask = None
		self._opsi_admin_gid = grp.getgrnam(OPSI_ADMIN_GROUP)[2]

		logger.comment("opsi pxe configuration service starting")

	def setConfig(self, config):
		logger.notice(u"Got new config")
		self.config = config

	def isRunning(self):
		return self._running

	def stop(self):
		logger.notice(u"Stopping opsipxeconfd main thread")

		try:
			self._startupTask.stop()
			self._startupTask.join(10)
		except AttributeError:
			pass  # Probably still set to None.
		except RuntimeError:
			pass  # Probably not yet started
		except Exception as error:
			logger.debug("Unhandled error during stop: '%s", error)

		self._running = False

		try:
			self._socket.close()
		except Exception as error:
			logger.error(u"Failed to close socket: %s", error)

	def reload(self):
		logger.notice(u"Reloading opsipxeconfd")
		init_logging(self.config)
		self._createBackendInstance()
		self._createSocket()


	def _createBackendInstance(self):
		logger.info(u"Creating backend instance")
		self._backend = BackendManager(
			dispatchConfigFile=self.config['dispatchConfigFile'],
			dispatchIgnoreModules=['OpsiPXEConfd'],  # Avoid loops
			backendConfigDir=self.config['backendConfigDir'],
			extend=True
		)
		self._backend.backend_setOptions({'addProductPropertyStateDefaults': True, 'addConfigStateDefaults': True})

	def _createSocket(self):
		return self._createUnixSocket()

	def _createUnixSocket(self):
		logger.notice(u"Creating unix socket %s", self.config['port'])
		if os.path.exists(self.config['port']):
			os.unlink(self.config['port'])
		self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		try:
			self._socket.bind(self.config['port'])
		except Exception as error:
			raise Exception(u"Failed to bind to socket '%s': %s" % (self.config['port'], error))
		self._socket.settimeout(0.1)
		self._socket.listen(self.config['maxConnections'])

		self._setAccessRightsForSocket(self.config['port'])

	def _setAccessRightsForSocket(self, path):
		logger.debug("Setting rights on socket '%s'", path)
		mode = os.stat(path)[0]
		# Adding read + write access for group and other.
		os.chmod(path, mode | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
		os.chown(path, -1, self._opsi_admin_gid)
		logger.debug("Done setting rights on socket '%s'", path)

	def _getConnection(self):
		try:
			sock, _ = self._socket.accept()
		except socket.error as error:
			if not self._running:
				return
			if error.args[0] == 'timed out' or error.args[0] == 11:
				return

			logger.debug("Socket error: {!r}".format(error))
			raise error
		logger.notice(u"Got connection from client")

		cc = None
		logger.info(u"Creating thread for connection %d", len(self._clientConnections) + 1)
		try:
			cc = ClientConnection(self, sock, self.clientConnectionCallback)
			with self._clientConnectionLock:
				self._clientConnections.append(cc)
			cc.start()
			logger.debug(u"Connection {!r} started.".format(cc.name))
		except Exception as error:
			logger.error(u"Failed to create control connection: %s", error)
			logger.logException(error)

			with self._clientConnectionLock:
				try:
					self._clientConnections.remove(cc)
				except ValueError:
					pass  # Element not in list

	def run(self):
		with log_context({'instance' : 'opsipxeconfd'}):
			self._running = True
			logger.notice(u"Starting opsipxeconfd main thread")
			try:
				self._createBackendInstance()
				logger.info("Setting needed boot configurations")
				self._startupTask = StartupTask(self)
				self._startupTask.start()
				self._createSocket()
				while self._running:
					self._getConnection()
				logger.notice(u"Opsipxeconfd main thread exiting...")
			except Exception as error:
				logger.logException(error)
			finally:
				self._running = False

	def clientConnectionCallback(self, connection):
		"""
		:type connection: ClientConnection
		"""
		logger.info(
			u"ClientConnection {!r} finished (took {:0.3f} seconds)".format(
			connection.name, (time.time() - connection.startTime))
		)

		try:
			with self._clientConnectionLock:
				try:
					self._clientConnections.remove(connection)
				except ValueError:
					pass  # Connection not in list

			logger.debug(u"ClientConnection '%s' removed", connection.name)
		except Exception as error:
			logger.error(u"Failed to remove ClientConnection: %s", error)

	def pxeConfigWriterCallback(self, pcw):
		"""
		:type pcw: PXEConfigWriter
		"""
		logger.info(
			u"PXEConfigWriter {!r} (for {!r}) finished (running for {:0.3f} seconds)".format(
			pcw.name, pcw.hostId, (time.time() - pcw.startTime))
		)

		try:
			with self._pxeConfigWritersLock:
				try:
					self._pxeConfigWriters.remove(pcw)
				except ValueError:
					pass  # Writer not in list
			logger.debug(u"PXE config writer removed")
		except Exception as error:
			logger.error(u"Failed to remove PXE config writer: %s", error)

		gotAlways = False
		for i, poc in enumerate(pcw.productOnClients):
			# renew objects and check if anythin changes on service since callback
			productOnClients = self._backend.productOnClient_getObjects(
				productType=u'NetbootProduct',
				clientId=poc.clientId,
				productId=poc.productId
			)
			if productOnClients:
				pcw.productOnClients[i] = productOnClients[0]
			else:
				del pcw.productOnClients[i]

			if pcw.productOnClients:
				pcw.productOnClients[i].setActionProgress(u'pxe boot configuration read')
				if pcw.productOnClients[i].getActionRequest() == u'always':
					gotAlways = True
				if pcw.templatefile != self.config['pxeConfTemplate'] and not gotAlways:
					pcw.productOnClients[i].setActionRequest(u'none')

		if pcw.productOnClients:
			self._backend.productOnClient_updateObjects(pcw.productOnClients)
		if gotAlways:
			self.updateBootConfiguration(pcw.hostId)

	def status(self):
		logger.notice(u"Getting opsipxeconfd status")
		result = u'opsipxeconfd status:\n'

		with self._clientConnectionLock:
			result += u'%s control connection(s) established\n' % len(self._clientConnections)
			for i, connection in enumerate(self._clientConnections, start=1):
				result += u'    Connection %s established at: %s\n' \
					% (i, time.asctime(time.localtime(connection.startTime)))

		result += u'\n%s boot configuration(s) set\n' % len(self._pxeConfigWriters)
		for pcw in self._pxeConfigWriters:
			result += u"Boot config for client '%s' (path '%s'; configuration %s) set since %s\n" % (
				pcw.hostId,
				pcw.pxefile,
				pcw.append,
				time.asctime(time.localtime(pcw.startTime))
			)
		logger.notice(result)
		return result

	def updateBootConfiguration(self, hostId, cacheFile=None):
		try:
			hostId = forceHostId(hostId)
			logger.info(u"Updating PXE boot configuration for host '%s'", hostId)

			self._removeCurrentConfigWriters(hostId)

			cachedData = self._readCachedData(cacheFile)
			if cachedData:
				logger.debug(u"Cached data read for %s: '%s'", hostId, cachedData)

			try:
				poc = cachedData["productOnClient"]
				if poc:
					productOnClients = [poc]
				else:
					productOnClients = None
			except KeyError:
				# Get product actions
				productOnClients = self._backend.productOnClient_getObjects(
					productType=u'NetbootProduct',
					clientId=hostId,
					actionRequest=['setup', 'uninstall', 'update', 'always', 'once', 'custom']
				)

			if not productOnClients:
				logger.info("No netboot products with action requests for client '%s' found.", hostId)
				return u'Boot configuration updated'

			try:
				host = cachedData["host"]
			except KeyError:
				host = self._getHostObject(hostId)

			depotId = self.config['depotId']

			newProductOnClients = []
			for poc in productOnClients:
				try:
					productOnDepot = cachedData["productOnDepot"]
				except KeyError:
					logger.debug("Searching for product '%s' on depot '%s'", poc.productId, depotId)
					productOnDepot = self._backend.productOnDepot_getObjects(
						productType=u'NetbootProduct',
						productId=poc.productId,
						depotId=depotId
					)

					try:
						productOnDepot = productOnDepot[0]
					except IndexError:
						logger.info(u"Product %s not available on depot '%s'", poc.productId, depotId)
						continue

				if productOnDepot:
					poc.productVersion = productOnDepot.productVersion
					poc.packageVersion = productOnDepot.packageVersion
					newProductOnClients.append(poc)

			productOnClients = newProductOnClients

			if not productOnClients:
				logger.info("No matching netboot product found on depot '%s'.", depotId)
				return u'Boot configuration updated'

			try:
				product = cachedData["product"]

				# Setting empty string to avoid making another
				# unnecessary call to the backend.
				elilo = cachedData['elilo'] or ''
			except KeyError:
				product = None
				elilo = None
				self._backend.backend_setOptions({'addProductPropertyStateDefaults': True, 'addConfigStateDefaults': True})

			pxeConfigTemplate, product = self._getPxeConfigTemplate(hostId, productOnClients, product, elilo)
			logger.debug(u"Using pxe config template '%s'", pxeConfigTemplate)

			pxeConfigName = self._getNameForPXEConfigFile(host)

			pxefile = os.path.join(self.config['pxeDir'], pxeConfigName)
			if os.path.exists(pxefile):
				for pcw in self._pxeConfigWriters:
					if pcw.uefi and not pcw._uefiModule:
						raise Exception(u"Should use uefi netboot, but uefi module is not licensed.")
					if pcw.pxefile == pxefile:
						if host.id == pcw.hostId:
							logger.notice(u"PXE boot configuration '%s' for client '%s' already exists.", pxefile, host.id)
							return
						else:
							raise Exception(u"PXE boot configuration '%s' already exists. Clients '%s' and '%s' using same address?"
											% (pxefile, host.id, pcw.hostId))
				logger.debug(u"PXE boot configuration '%s' already exists, removing.", pxefile)
				os.unlink(pxefile)

			try:
				serviceAddress = cachedData['serviceAddress']
			except KeyError:
				serviceAddress = self._getConfigServiceAddress(hostId)

			# Append arguments
			append = {
				'pckey': host.getOpsiHostKey(),
				'hn': hostId.split('.')[0],
				'dn': u'.'.join(hostId.split('.')[1:]),
				'product': product.id,
				'service': serviceAddress,
			}
			if append['pckey']:
				logger.addConfidentialString(append['pckey'])

			try:
				bootimageAppendConfigStates = [cachedData['bootimageAppend']]
				bootimageAppend = self._getAdditionalBootimageParameters(hostId, bootimageAppendConfigStates)
			except KeyError:
				bootimageAppend = self._getAdditionalBootimageParameters(hostId)

			for key, value in bootimageAppend:
				append[key] = value

			# Get product property states
			try:
				productPropertyStates = cachedData["productPropertyStates"]
			except KeyError:
				productIds = [poc.productId for poc in productOnClients]
				if productIds:
					productPropertyStates = {
						pps.propertyId: u','.join(forceUnicodeList(pps.getValues()))
						for pps in self._backend.productPropertyState_getObjects(
							objectId=hostId,
							productId=productIds
						)
					}
				else:
					productPropertyStates = {}

			pcw = None
			try:
				logger.info(u"Creating thread for pxeconfig %d", len(self._pxeConfigWriters) + 1)
				try:
					backendInfo = cachedData["backendInfo"]
				except KeyError:
					backendInfo = self._backend.backend_info()
					backendInfo['hostCount'] = len(self._backend.host_getIdents(type='OpsiClient'))

				pcw = PXEConfigWriter(pxeConfigTemplate, hostId, productOnClients, append, productPropertyStates, pxefile, self.pxeConfigWriterCallback, backendInfo)
				with self._pxeConfigWritersLock:
					self._pxeConfigWriters.append(pcw)
				pcw.start()
				logger.notice(u"PXE boot configuration for host %s is now set at '%s'", hostId, pxefile)
				return u'Boot configuration updated'
			except Exception as error:
				logger.error(u"Failed to create pxe config writer: %s", error)

				with self._pxeConfigWritersLock:
					try:
						self._pxeConfigWriters.remove(pcw)
					except ValueError:
						pass  # Writer not in list

				raise
		except Exception as error:
			logger.logException(error)
			raise error

	def _removeCurrentConfigWriters(self, hostId):
		"""
		Remove eventually running PXE config writers for the given `hostId`.
		"""
		with self._pxeConfigWritersLock:
			currentPcws = [pcw for pcw in self._pxeConfigWriters if pcw.hostId == hostId]

			for pcw in currentPcws:
				self._pxeConfigWriters.remove(pcw)

		logger.debug("Removing %s existing config writers for '%s'", len(currentPcws), hostId)

		for pcw in currentPcws:
			pcw.stop()

			for _ in range(10):
				if not pcw.is_alive():
					break

				time.sleep(0.1)
			else:
				pcw.join(1)

			logger.notice(u"PXE boot configuration for host '%s' removed", hostId)

	@staticmethod
	def _readCachedData(cacheFile):
		if not cacheFile:
			return {}
		elif not os.path.exists(cacheFile):
			return {}

		logger.debug("Reading data from %s", cacheFile)
		with codecs.open(cacheFile, "r", 'utf-8') as inFile:
			data = json.load(inFile)
		os.unlink(cacheFile)

		return deserialize(data)

	def _getHostObject(self, hostId):
		"""
		Get the object for `hostId`.
		"""
		logger.debug("Searching for host with id '%s'", hostId)

		host = self._backend.host_getObjects(id=hostId)
		try:
			return host[0]
		except IndexError:
			raise ValueError(u"Host '%s' not found" % hostId)

	def _getPxeConfigTemplate(self, hostId, productOnClients, product=None, elilo=None):
		"""
		Get the pxe template to use for `hostId`

		:type hostId: str
		:raises BackendMissingDataError: In case no matching product is found.
		:rtype: str
		:returns: The absolute path to the template that should be used for the client.
		"""
		if elilo is None:
			elilo = self._detectEliloMode(hostId)

		pxeConfigTemplate = None
		for poc in productOnClients:
			if not product:
				try:
					product = self._backend.product_getObjects(
						type=u'NetbootProduct',
						id=poc.productId,
						productVersion=poc.productVersion,
						packageVersion=poc.packageVersion
					)[0]
				except IndexError:
					product = None

			if not product:
				raise BackendMissingDataError(u"Product not found: %s_%s-%s" % (poc.productId, poc.productVersion, poc.packageVersion))

			if ELILO_X86 == elilo:
				pxeConfigTemplate = self.config['uefiConfTemplate-x86']
			elif ELILO_X64 == elilo:
				pxeConfigTemplate = self.config['uefiConfTemplate-x64']

			if product.pxeConfigTemplate:
				if pxeConfigTemplate and (pxeConfigTemplate != product.pxeConfigTemplate):
					logger.error(
						u"Cannot use more than one pxe config template, got: %s, %s",
						pxeConfigTemplate, product.pxeConfigTemplate
					)
					absolutePathToTemplate = os.path.join(os.path.dirname(self.config['pxeConfTemplate']), product.pxeConfigTemplate)
					if os.path.isfile("%s.efi" % absolutePathToTemplate):
						logger.notice(u"Using an alternate UEFI template provided by netboot product")
						pxeConfigTemplate = "%s.efi" % product.pxeConfigTemplate
					else:
						logger.notice(u"Did not find any alternate UEFI pxeConfigTemplate, will use the default UEFI template")

				else:
					pxeConfigTemplate = product.pxeConfigTemplate
					logger.notice(
						u"Special pxe config template '%s' will be used used for host '%s', product '%s'",
						pxeConfigTemplate, hostId, poc.productId
					)

		if not pxeConfigTemplate:
			logger.debug("Using default config template")
			pxeConfigTemplate = self.config['pxeConfTemplate']

		if not os.path.isabs(pxeConfigTemplate):  # Not an absolute path
			logger.debug("pxeConfigTemplate is not an absolute path.")
			pxeConfigTemplate = os.path.join(os.path.dirname(self.config['pxeConfTemplate']), pxeConfigTemplate)
			logger.debug("pxeConfigTemplate changed to %s", pxeConfigTemplate)

		return pxeConfigTemplate, product

	def _detectEliloMode(self, hostId):
		"""
		Checks if elilo mode is set for client.

		:rtype: str or None
		:returns: The elilo mode of the client represented as either
`x86` or `x64` if it is set. If no elilo mode is set then `None`.
		"""
		eliloMode = None
		configStates = self._backend.configState_getObjects(configId="clientconfig.dhcpd.filename", objectId=hostId)
		if configStates:
			val = configStates[0].getValues()
			if val and (('elilo' in val[0]) or ('shimx64' in val[0])):
				if 'x86' in val[0]:
					eliloMode = ELILO_X86
				else:
					eliloMode = ELILO_X64

		return eliloMode

	@staticmethod
	def _getNameForPXEConfigFile(host):
		if host.getHardwareAddress():
			logger.debug(u"Got hardware address '%s' for host '%s'", host.getHardwareAddress(), host.id)
			return u"01-%s" % host.getHardwareAddress().replace(u':', u'-')
		elif host.getIpAddress():
			logger.warning(u"Failed to get hardware address for host '%s', using ip address '%s'", host.id, host.getIpAddress())
			return '%02X%02X%02X%02X' % tuple([int(i) for i in host.getIpAddress().split('.')])
		else:
			raise Exception(u"Neither hardware address nor ip address known for host '%s'" % host.id)

	def _getConfigServiceAddress(self, hostId):
		"""
		Returns the config serive address for `hostId`.
		"""
		address = u''

		configStates = self._backend.configState_getObjects(objectId=hostId, configId=u'clientconfig.configserver.url')
		if configStates:
			address = configStates[0].getValues()[0]

		if not address.endswith(u'/rpc'):
			address += u'/rpc'

		return address

	def _getAdditionalBootimageParameters(self, hostId, configStates=None):
		"""
		Returns any additional bootimage parameters that may be set for `hostId`.
		"""
		if configStates is None:
			configStates = self._backend.configState_getObjects(objectId=hostId, configId=u'opsi-linux-bootimage.append')

		if configStates:
			app = u' '.join(forceUnicodeList(configStates[0].getValues()))
			for option in app.split():
				keyValue = option.split(u"=")
				if len(keyValue) < 2:
					yield keyValue[0].strip().lower(), u''
				else:
					yield keyValue[0].strip().lower(), keyValue[1].strip()
