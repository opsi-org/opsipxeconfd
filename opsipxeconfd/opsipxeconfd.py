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

from __future__ import print_function

import base64
import codecs
import json
import getopt
import grp
import os
import socket
import stat
import sys
import threading
import time
from contextlib import contextmanager, closing
from shlex import split as shlex_split
from signal import SIGHUP, SIGINT, SIGTERM, signal
from hashlib import md5

from OPSI.Backend.BackendManager import BackendManager
from OPSI.Backend.OpsiPXEConfd import ERROR_MARKER, ServerConnection
from OPSI.Config import OPSI_ADMIN_GROUP
from OPSI.Exceptions import BackendMissingDataError
from OPSI.Logger import LOG_NONE, LOG_NOTICE, LOG_WARNING, Logger
from OPSI.System.Posix import execute, which
from OPSI.Util import deserialize, getfqdn, getPublicKey
from OPSI.Util.File import ConfigFile
from OPSI.Types import (forceFilename, forceHostId, forceInt, forceUnicode,
	forceUnicodeList)

__version__ = '4.2.0.6'

ELILO_X86 = 'x86'
ELILO_X64 = 'x64'
OPSI_ADMIN_GROUP_ID = grp.getgrnam(OPSI_ADMIN_GROUP)[2]

logger = Logger()


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

		self._setOpsiLogging()
		logger.comment("""\
==================================================================
=           opsi pxe configuration service starting              =
==================================================================""")

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
			logger.debug("Unhandled error during stop: {0!r}", error)

		try:
			self._socket.close()
		except Exception as error:
			logger.error(u"Failed to close socket: {0}", error)

		self._running = False

	def reload(self):
		logger.notice(u"Reloading opsipxeconfd")
		self._setOpsiLogging()
		self._createBackendInstance()
		self._createSocket()

	def _setOpsiLogging(self):
		if self.config['logFile']:
			logger.setLogFile(self.config['logFile'])
		if self.config['logFormat']:
			logger.setLogFormat(self.config['logFormat'])
		logger.setFileLevel(self.config['logLevel'])

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
		logger.notice(u"Creating unix socket {0!r}", self.config['port'])
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

	@staticmethod
	def _setAccessRightsForSocket(path):
		logger.debug("Setting rights on socket {0!r}", path)
		mode = os.stat(path)[0]
		# Adding read + write access for group and other.
		os.chmod(path, mode | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
		os.chown(path, -1, OPSI_ADMIN_GROUP_ID)
		logger.debug("Done setting rights on socket {0!r}", path)

	def _getConnection(self):
		try:
			sock, _ = self._socket.accept()
		except socket.error as error:
			if error.args[0] == 'timed out' or error.args[0] == 11:
				return

			logger.debug("Socket error: {!r}".format(error))
			raise error
		logger.notice(u"Got connection from client")

		cc = None
		logger.info(u"Creating thread for connection {0}", len(self._clientConnections) + 1)
		try:
			cc = ClientConnection(self, sock, self.clientConnectionCallback)
			with self._clientConnectionLock:
				self._clientConnections.append(cc)
			cc.start()
			logger.debug(u"Connection {!r} started.".format(cc.name))
		except Exception as error:
			logger.error(u"Failed to create control connection: {0}", error)
			logger.logException(error)

			with self._clientConnectionLock:
				try:
					self._clientConnections.remove(cc)
				except ValueError:
					pass  # Element not in list

	def run(self):
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
			u"ClientConnection {!r} finished (took {:0.3f} seconds)",
			connection.name, (time.time() - connection.startTime)
		)

		try:
			with self._clientConnectionLock:
				try:
					self._clientConnections.remove(connection)
				except ValueError:
					pass  # Connection not in list

			logger.debug(u"ClientConnection {!r} removed", connection.name)
		except Exception as error:
			logger.error(u"Failed to remove ClientConnection: {0}", error)

	def pxeConfigWriterCallback(self, pcw):
		"""
		:type pcw: PXEConfigWriter
		"""
		logger.info(
			u"PXEConfigWriter {!r} (for {!r}) finished (running for {:0.3f} seconds)",
			pcw.name, pcw.hostId, (time.time() - pcw.startTime)
		)

		try:
			with self._pxeConfigWritersLock:
				try:
					self._pxeConfigWriters.remove(pcw)
				except ValueError:
					pass  # Writer not in list
			logger.debug(u"PXE config writer removed")
		except Exception as error:
			logger.error(u"Failed to remove PXE config writer: {0}", error)

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
			logger.info(u"Updating PXE boot configuration for host {0!r}", hostId)

			self._removeCurrentConfigWriters(hostId)

			cachedData = self._readCachedData(cacheFile)
			if cachedData:
				logger.debug(u"Cached data read for {}: {!r}", hostId, cachedData)

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
				logger.info("No netboot products with action requests for client {0!r} found.", hostId)
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
					logger.debug("Searching for product {!r} on depot {!r}", poc.productId, depotId)
					productOnDepot = self._backend.productOnDepot_getObjects(
						productType=u'NetbootProduct',
						productId=poc.productId,
						depotId=depotId
					)

					try:
						productOnDepot = productOnDepot[0]
					except IndexError:
						logger.info(u"Product {} not available on depot {!r}", poc.productId, depotId)
						continue

				if productOnDepot:
					poc.productVersion = productOnDepot.productVersion
					poc.packageVersion = productOnDepot.packageVersion
					newProductOnClients.append(poc)

			productOnClients = newProductOnClients

			if not productOnClients:
				logger.info("No matching netboot product found on depot {0!r}.", depotId)
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
			logger.debug(u"Using pxe config template {0!r}", pxeConfigTemplate)

			pxeConfigName = self._getNameForPXEConfigFile(host)

			pxefile = os.path.join(self.config['pxeDir'], pxeConfigName)
			if os.path.exists(pxefile):
				for pcw in self._pxeConfigWriters:
					if pcw.uefi and not pcw._uefiModule:
						raise Exception(u"Should use uefi netboot, but uefi module is not licensed.")
					if pcw.pxefile == pxefile:
						if host.id == pcw.hostId:
							logger.notice(u"PXE boot configuration {0!r} for client {1!r} already exists.", pxefile, host.id)
							return
						else:
							raise Exception(u"PXE boot configuration '%s' already exists. Clients '%s' and '%s' using same address?"
											% (pxefile, host.id, pcw.hostId))
				logger.debug(u"PXE boot configuration {0!r} already exists, removing.", pxefile)
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
				logger.info(u"Creating thread for pxeconfig {0}", len(self._pxeConfigWriters) + 1)
				try:
					backendInfo = cachedData["backendInfo"]
				except KeyError:
					backendInfo = self._backend.backend_info()
					backendInfo['hostCount'] = len(self._backend.host_getIdents(type='OpsiClient'))

				pcw = PXEConfigWriter(pxeConfigTemplate, hostId, productOnClients, append, productPropertyStates, pxefile, self.pxeConfigWriterCallback, backendInfo)
				with self._pxeConfigWritersLock:
					self._pxeConfigWriters.append(pcw)
				pcw.start()
				logger.notice(u"PXE boot configuration for host {0} is now set at {1!r}", hostId, pxefile)
				return u'Boot configuration updated'
			except Exception as error:
				logger.error(u"Failed to create pxe config writer: {0}", error)

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

		logger.debug("Removing {} existing config writers for {!r}", len(currentPcws), hostId)

		for pcw in currentPcws:
			pcw.stop()

			for _ in range(10):
				if not pcw.is_alive():
					break

				time.sleep(0.1)
			else:
				pcw.join(1)

			logger.notice(u"PXE boot configuration for host {0!r} removed", hostId)

	@staticmethod
	def _readCachedData(cacheFile):
		if not cacheFile:
			return {}
		elif not os.path.exists(cacheFile):
			return {}

		logger.debug("Reading data from {}", cacheFile)
		with codecs.open(cacheFile, "r", 'utf-8') as inFile:
			data = json.load(inFile)
		os.unlink(cacheFile)

		return deserialize(data)

	def _getHostObject(self, hostId):
		"""
		Get the object for `hostId`.
		"""
		logger.debug("Searching for host with id {!r}", hostId)

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
				if not elilo:
					if pxeConfigTemplate and (pxeConfigTemplate != product.pxeConfigTemplate):
						logger.error(
							u"Cannot use more than one pxe config template, got: {0}, {1}",
							pxeConfigTemplate, product.pxeConfigTemplate
						)
					else:
						pxeConfigTemplate = product.pxeConfigTemplate
						logger.notice(
							u"Special pxe config template {0!r} will be used used for host {1!r}, product {2!r}",
							pxeConfigTemplate, hostId, poc.productId
						)
				else:
					logger.notice("Ignoring given pxeConfigTemplate because uefi detected for the client.")

		if not pxeConfigTemplate:
			logger.debug("Using default config template")
			pxeConfigTemplate = self.config['pxeConfTemplate']

		if not os.path.isabs(pxeConfigTemplate):  # Not an absolute path
			logger.debug("pxeConfigTemplate is not an absolute path.")
			pxeConfigTemplate = os.path.join(os.path.dirname(self.config['pxeConfTemplate']), pxeConfigTemplate)
			logger.debug("pxeConfigTemplate changed to {0}", pxeConfigTemplate)

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
			if val and 'elilo' in val[0]:
				if 'x86' in val[0]:
					eliloMode = ELILO_X86
				else:
					eliloMode = ELILO_X64

		return eliloMode

	@staticmethod
	def _getNameForPXEConfigFile(host):
		if host.getHardwareAddress():
			logger.debug(u"Got hardware address {0!r} for host {1!r}", host.getHardwareAddress(), host.id)
			return u"01-%s" % host.getHardwareAddress().replace(u':', u'-')
		elif host.getIpAddress():
			logger.warning(u"Failed to get hardware address for host {0!r}, using ip address {1!r}", host.id, host.getIpAddress())
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


class StartupTask(threading.Thread):
	def __init__(self, opsipxeconfd):
		threading.Thread.__init__(self)
		self._opsipxeconfd = opsipxeconfd
		self._running = False
		self._stop = False

	def run(self):
		self._running = True
		logger.notice(u"Start setting initial boot configurations")
		try:
			clientIds = [clientToDepot['clientId'] for clientToDepot in
						self._opsipxeconfd._backend.configState_getClientToDepotserver(depotIds=[self._opsipxeconfd.config['depotId']])]

			if clientIds:
				productOnClients = self._opsipxeconfd._backend.productOnClient_getObjects(
					productType=u'NetbootProduct',
					clientId=clientIds,
					actionRequest=['setup', 'uninstall', 'update', 'always', 'once', 'custom']
				)

				clientIds = set()
				for poc in productOnClients:
					clientIds.add(poc.clientId)

				for clientId in clientIds:
					if self._stop:
						return

					try:
						self._opsipxeconfd.updateBootConfiguration(clientId)
					except Exception as error:
						logger.error(u"Failed to update PXE boot config for client {0!r}: {1}", clientId, error)

			logger.notice(u"Finished setting initial boot configurations")
		except Exception as error:
			logger.logException(error)
		finally:
			self._running = False

	def stop(self):
		self._stop = True


class PXEConfigWriter(threading.Thread):
	def __init__(self, templatefile, hostId, productOnClients, append, productPropertyStates, pxefile, callback=None, backendinfo=None):
		threading.Thread.__init__(self)
		self.templatefile = templatefile
		self.append = append
		self.productPropertyStates = productPropertyStates
		self.hostId = hostId
		self.productOnClients = productOnClients
		self.pxefile = pxefile
		self._callback = callback
		self.startTime = time.time()
		self._running = False
		self._pipe = None
		self.uefi = False
		self._uefiModule = False
		self._secureBootModule = False
		self._usingGrub = False

		if backendinfo:  # expect this to be a dict
			modules = backendinfo['modules']
			helpermodules = backendinfo['realmodules']
			hostCount = backendinfo['hostCount']

			if modules.get('customer'):
				publicKey = getPublicKey(data=base64.decodebytes(b'AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDojY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDUlk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP'))
				data = u''
				for module in sorted(list(modules.keys())):
					if module in ('valid', 'signature'):
						continue
					if module in helpermodules:
						val = helpermodules[module]
						if module == 'uefi':
							if int(val) + 50 <= hostCount:
								logger.error(u"UNDERLICENSED: You have more Clients then licensed in modules file. Disabling module: {0!r}", module)
								modules[module] = False
							elif int(val) <= hostCount:
								logger.warning("UNDERLICENSED WARNING: You have more Clients then licensed in modules file.")
						else:
							if int(val) > 0:
								modules[module] = True
					else:
						val = modules[module]
						if val is False:
							val = 'no'
						if val is True:
							val = 'yes'
					data += u'%s = %s\r\n' % (module.lower().strip(), val)

				if not bool(publicKey.verify(md5(data.encode()).digest(), [int(modules['signature'])])):
					logger.error(u"Failed to verify modules signature")
					return

				if modules.get('uefi'):
					self._uefiModule = True
				if modules.get('secureboot'):
					self._secureBootModule = True

		logger.info(u"PXEConfigWriter initializing: templatefile {0!r}, pxefile {1!r}, hostId {2!r}, append {3}",
					self.templatefile, self.pxefile, self.hostId, self.append)

		if not os.path.exists(self.templatefile):
			raise Exception(u"Template file '%s' not found" % self.templatefile)

		self.template = {'pxelinux': []}

		# Set pxe config content
		self.content = self._getPXEConfigContent(self.templatefile)

		try:
			del self.append['pckey']
		except KeyError:
			pass  # Key may be non-existing

		if os.path.exists(self.pxefile):
			os.unlink(self.pxefile)
		os.mkfifo(self.pxefile)
		os.chmod(self.pxefile, 0o644)

	def _getPXEConfigContent(self, templateFile):
		logger.debug(u"Reading template {!r}", templateFile)
		with open(templateFile, 'r') as infile:
			templateLines = infile.readlines()

		content = u''
		appendLineProperties = []
		for line in templateLines:
			line = line.rstrip()

			for (propertyId, value) in self.productPropertyStates.items():
				logger.debug2("Property: {0!r}: value: {1!r}", propertyId, value)
				line = line.replace(u'%%%s%%' % propertyId, value)

			if line.lstrip().startswith(u'append'):
				if line.lstrip().startswith(u'append='):
					logger.notice("elilo configuration detected for {}", self.hostId)
					self.uefi = True
					appendLineProperties = ''.join(line.split('="')[1:])[:-1].split()
				else:
					self.uefi = False
					appendLineProperties = line.lstrip().split()[1:]

				for key, value in self.append.items():
					if value:
						appendLineProperties.append("%s=%s" % (key, value))
					else:
						appendLineProperties.append(str(key))

				if self._uefiModule and self.uefi:
					content = '%sappend="%s"\n' % (content, ' '.join(appendLineProperties))
				elif not self._uefiModule and self.uefi:
					raise Exception(u"You have not licensed uefi module, please check your modules or contact info@uib.de")
				else:
					content = '%s  append %s\n' % (content, ' '.join(appendLineProperties))
			elif line.lstrip().startswith(u'linux'):
				logger.notice("UEFI GRUB configuration detected for {}", self.hostId)
				if not self._secureBootModule:
					raise Exception(u"You have not licensed the secureboot module, please check your modules or contact info@uib.de")

				self.uefi = True
				self._usingGrub = True
				appendLineProperties = line.lstrip().split()[1:]
				for key, value in self.append.items():
					if value:
						appendLineProperties.append("%s=%s" % (key, value))
					else:
						appendLineProperties.append(str(key))

				content = '%slinux %s\n' % (content, ' '.join(appendLineProperties))
			else:
				content = "%s%s\n" % (content, line)

		return content

	def run(self):
		self._running = True
		pipeOpenend = False
		while self._running and not pipeOpenend:
			try:
				self._pipe = os.open(self.pxefile, os.O_WRONLY | os.O_NONBLOCK)
				pipeOpenend = True
			except Exception as error:
				if error.errno != 6:
					raise
				time.sleep(1)

		if pipeOpenend:
			logger.notice(u"Pipe {0!r} opened, piping pxe boot configuration", self.pxefile)
			os.write(self._pipe, self.content.encode())
			if self.uefi and self._usingGrub:
				time.sleep(5)
			os.close(self._pipe)

		if os.path.exists(self.pxefile):
			os.unlink(self.pxefile)

		if pipeOpenend and self._callback:
			self._callback(self)

	def stop(self):
		self._running = False


class ClientConnection(threading.Thread):
	def __init__(self, opsipxeconfd, connectionSocket, callback=None):
		threading.Thread.__init__(self)
		self._opsipxeconfd = opsipxeconfd
		self._socket = connectionSocket
		self._callback = callback
		self._running = False
		self.startTime = time.time()

	def run(self):
		self._running = True
		self._socket.settimeout(2.0)

		logger.debug("Receiving data...")
		with closing(self._socket):
			try:
				cmd = self._socket.recv(4096)
				cmd = forceUnicode(cmd.strip())
				logger.info(u"Got command {0!r}", cmd)

				result = self._processCommand(cmd)
				logger.info(u"Returning result {0!r}", result)

				try:
					self._socket.send(result.encode('utf-8'))
				except Exception as error:
					logger.warning("Sending result over socket failed: {0!r}", error)
			finally:
				if self._running and self._callback:
					self._callback(self)

	def stop(self):
		self._running = False
		try:
			self._socket.close()
		except AttributeError:
			pass  # Probably none

	def _processCommand(self, cmd):
		try:
			try:
				command, arguments = cmd.split(None, 1)
				arguments = shlex_split(arguments)
			except ValueError:
				command = cmd.split()[0]

			command = command.strip()

			if command == u'stop':
				self._opsipxeconfd.stop()
				return u'opsipxeconfd is going down'
			elif command == u'status':
				return self._opsipxeconfd.status()
			elif command == u'update':
				if len(arguments) == 2:
					# We have an update path
					hostId = forceHostId(arguments[0])
					cacheFilePath = forceFilename(arguments[1])
					return self._opsipxeconfd.updateBootConfiguration(hostId, cacheFilePath)
				elif len(arguments) == 1:
					hostId = forceHostId(arguments[0])
					return self._opsipxeconfd.updateBootConfiguration(hostId)
				else:
					raise ValueError(u"bad arguments for command 'update', needs <hostId>")

			raise ValueError(u"Command '%s' not supported" % cmd)
		except Exception as error:
			logger.error("Processing command {!r} failed: {}", cmd, error)
			return u'%s: %s' % (ERROR_MARKER, error)


class OpsipxeconfdInit(object):
	def __init__(self):
		logger.debug(u"OpsiPXEConfdInit")
		# Set umask
		os.umask(0o077)
		self._pid = 0

		try:
			(self.opts, self.args) = getopt.getopt(sys.argv[1:], "vFl:c:", ["no-fork", "loglevel=", "conffile="])
		except getopt.GetoptError:
			self.usage()
			sys.exit(1)

		if len(self.args) < 1:
			self.usage()
			sys.exit(1)

		self.config = {}
		self.setDefaultConfig()
		# Process command line arguments
		for (opt, arg) in self.opts:
			if opt in ("-c", '--conffile'):
				self.config['configFile'] = forceFilename(arg)
			elif opt == "-v":
				print(u"opsipxeconfd version %s" % __version__)
				sys.exit(0)
		self.readConfigFile()
		self.setCommandlineConfig()

		if self.args[0] == u'version':
			print(__version__)
			sys.exit(0)

		elif self.args[0] == u'start':
			# Call signalHandler on signal SIGHUP, SIGTERM, SIGINT
			signal(SIGHUP, self.signalHandler)
			signal(SIGTERM, self.signalHandler)
			signal(SIGINT, self.signalHandler)

			if self.config['daemon']:
				logger.setConsoleLevel(LOG_NONE)
				self.daemonize()
			else:
				logger.setConsoleLevel(self.config['logLevel'])
				logger.setConsoleColor(True)

			with temporaryPidFile(self.config['pidFile']):
				self._opsipxeconfd = Opsipxeconfd(self.config)
				self._opsipxeconfd.start()
				time.sleep(3)
				while self._opsipxeconfd.isRunning():
					time.sleep(1)
				self._opsipxeconfd.join(30)

		else:
			con = ServerConnection(self.config['port'], timeout=5.0)
			result = con.sendCommand(u' '.join(forceUnicodeList(self.args)))
			if result:
				if result.startswith(u'(ERROR)'):
					print(result, file=sys.stderr)
					sys.exit(1)
				print(result, file=sys.stdout)
				sys.exit(0)
			else:
				sys.exit(1)

	def setDefaultConfig(self):
		self.config = {
			'pidFile': u'/var/run/opsipxeconfd/opsipxeconfd.pid',
			'configFile': u'/etc/opsi/opsipxeconfd.conf',
			'depotId': forceHostId(getfqdn()),
			'daemon': True,
			'logLevel': LOG_NOTICE,
			'logFile': u'/var/log/opsi/opsipxeconfd.log',
			'logFormat': u'[%l] [%D] %M (%F|%N)',
			'port': u'/var/run/opsipxeconfd/opsipxeconfd.socket',
			'pxeDir': u'/tftpboot/linux/pxelinux.cfg',
			'pxeConfTemplate': u'/tftpboot/linux/pxelinux.cfg/install',
			'uefiConfTemplate-x64': u'/tftpboot/linux/pxelinux.cfg/install-elilo-x64',
			'uefiConfTemplate-x86': u'/tftpboot/linux/pxelinux.cfg/install-elilo-x86',
			'maxConnections': 5,
			'maxPxeConfigWriters': 100,
			'backendConfigDir': u'/etc/opsi/backends',
			'dispatchConfigFile': u'/etc/opsi/backendManager/dispatch.conf',
		}

	def setCommandlineConfig(self):
		for (opt, arg) in self.opts:
			if opt in ("-F", "--no-fork"):
				self.config['daemon'] = False
			if opt in ("-l", "--loglevel"):
				self.config['logLevel'] = forceInt(arg)

	def signalHandler(self, signo, stackFrame):
		for thread in threading.enumerate():
			logger.debug(u"Running thread before signal: {0}", thread)

		logger.debug(u"Processing signal {0!r}", signo)
		if signo == SIGHUP:
			self.setDefaultConfig()
			self.readConfigFile()
			self.setCommandlineConfig()

			try:
				self._opsipxeconfd.setConfig(self.config)
				self._opsipxeconfd.reload()
			except AttributeError:
				pass  # probably set to None
		elif signo in (SIGTERM, SIGINT):
			try:
				self._opsipxeconfd.stop()
			except AttributeError:
				pass  # probably set to None

		for thread in threading.enumerate():
			logger.debug(u"Running thread after signal: {0}", thread)

	def readConfigFile(self):
		''' Get settings from config file '''
		logger.notice(u"Trying to read config from file: {0!r}", self.config['configFile'])

		try:
			configFile = ConfigFile(filename=self.config['configFile'])
			for line in configFile.parse():
				if '=' not in line:
					logger.error(u"Parse error in config file: {0!r}, line {1}: '=' not found", self.config['configFile'], line)
					continue

				(option, value) = line.split(u'=', 1)
				option = option.strip()
				value = value.strip()
				if option == 'pid file':
					self.config['pidFile'] = forceFilename(value)
				elif option == 'log level':
					self.config['logLevel'] = forceInt(value)
				elif option == 'log file':
					self.config['logFile'] = forceFilename(value)
				elif option == 'log format':
					self.config['logFormat'] = forceUnicode(value)
				elif option == 'pxe config dir':
					self.config['pxeDir'] = forceFilename(value)
				elif option == 'pxe config template':
					self.config['pxeConfTemplate'] = forceFilename(value)
				elif option == 'uefi netboot config template x86':
					self.config['uefiConfTemplate-x86'] = forceFilename(value)
				elif option == 'uefi netboot config template x64':
					self.config['uefiConfTemplate-x64'] = forceFilename(value)
				elif option == 'max pxe config writers':
					self.config['maxPxeConfigWriters'] = forceInt(value)
				elif option == 'max control connections':
					self.config['maxConnections'] = forceInt(value)
				elif option == 'backend config dir':
					self.config['backendConfigDir'] = forceFilename(value)
				elif option == 'dispatch config file':
					self.config['dispatchConfigFile'] = forceFilename(value)
				else:
					logger.warning(u"Ignoring unknown option {0!r} in config file: {1!r}", option, self.config['configFile'])

		except Exception as error:
			# An error occured while trying to read the config file
			logger.error(u"Failed to read config file {0!r}: {1}", self.config['configFile'], error)
			logger.logException(error)
			raise
		logger.notice(u"Config read")

	@staticmethod
	def usage():
		print(u"\nUsage: %s [options] <command> [clientId] [args]..." % os.path.basename(sys.argv[0]))
		print(u"Commands:")
		print(u"  version         Show version information and exit")
		print(u"  start           Start main process")
		print(u"  stop            Stop main process")
		print(u"  status          Print status information of the main process")
		print(u"  update          update PXE boot configuration for client")
		print(u"Options:")
		print(u"  -F, --no-fork   Do not fork to background")
		print(u"  -c, --conffile  Location of config file")
		print(u"  -l, --loglevel  Set log level (default: 5)")
		print(u"        0=comment, 1=essential, 2=critical, 3=error, 4=warning, 5=notice, 6=info, 7=debug, 8=debug2, 9=confidential")
		print(u"")

	def daemonize(self):
		# Fork to allow the shell to return and to call setsid
		try:
			self._pid = os.fork()
			if self._pid > 0:
				# Parent exits
				sys.exit(0)
		except OSError as error:
			raise Exception(u"First fork failed: %e" % error)

		# Do not hinder umounts
		os.chdir("/")
		# Create a new session
		os.setsid()

		# Fork a second time to not remain session leader
		try:
			self._pid = os.fork()
			if self._pid > 0:
				sys.exit(0)
		except OSError as error:
			raise Exception(u"Second fork failed: %e" % error)

		logger.setConsoleLevel(LOG_NONE)

		# Close standard output and standard error.
		os.close(0)
		os.close(1)
		os.close(2)

		# Open standard input (0)
		if hasattr(os, "devnull"):
			os.open(os.devnull, os.O_RDWR)
		else:
			os.open("/dev/null", os.O_RDWR)

		# Duplicate standard input to standard output and standard error.
		os.dup2(0, 1)
		os.dup2(0, 2)
		sys.stdout = logger.getStdout()
		sys.stderr = logger.getStderr()


@contextmanager
def temporaryPidFile(filepath):
	'''
	Create a file containing the current pid for 'opsipxeconfd' at `filepath`.
	Leaving the context will remove the file.
	'''
	pidFile = filepath

	logger.debug("Reading old pidFile {0!r}...", pidFile)
	try:
		with open(pidFile, 'r') as pf:
			oldPid = pf.readline().strip()

		if oldPid:
			running = False
			try:
				pids = execute("%s -x opsipxeconfd" % which("pidof"))[0].strip().split()
				for runningPid in pids:
					if runningPid == oldPid:
						running = True
						break
			except Exception as error:
				logger.error(error)

			if running:
				raise Exception(u"Another opsipxeconfd process is running (pid: %s), stop process first or change pidfile." % oldPid)
	except IOError as ioerr:
		if ioerr.errno != 2:  # errno 2 == no such file
			raise ioerr

	logger.info(u"Creating pid file {0!r}", pidFile)
	pid = os.getpid()
	with open(pidFile, "w") as pf:
		pf.write(str(pid))

	try:
		yield
	finally:
		try:
			logger.debug(u"Removing pid file {0!r}...")
			os.unlink(pidFile)
			logger.info(u"Removed pid file {0!r}", pidFile)
		except OSError as oserr:
			if oserr.errno != 2:
				logger.error(u"Failed to remove pid file {0!r}: {1}", pidFile, oserr)
		except Exception as error:
			logger.error(u"Failed to remove pid file {0!r}: {1}", pidFile, error)


# if __name__ == "__main__":
def main():
	logger.setConsoleLevel(LOG_WARNING)

	try:
		OpsipxeconfdInit()
	except SystemExit:
		pass
	except Exception as exception:
		logger.logException(exception)
		print(u"ERROR: %s" % exception, file=sys.stderr)
		sys.exit(1)
