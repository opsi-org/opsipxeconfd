# -*- coding: utf-8 -*-

# opsipxeconfd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2013-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

"""
opsipxeconfd
"""

import os
import grp
import json
import stat
import time
import base64
import codecs
import socket
import threading
from typing import Dict, List, Any, Tuple

try:
	# python3-pycryptodome installs into Cryptodome
	from Cryptodome.Hash import MD5  # type: ignore
	from Cryptodome.Signature import pkcs1_15  # type: ignore
except ImportError:
	# PyCryptodome from pypi installs into Crypto
	from Crypto.Hash import MD5
	from Crypto.Signature import pkcs1_15

from opsicommon.logging import logger, log_context, secret_filter

from OPSI.Backend.BackendManager import BackendManager
from OPSI.Config import OPSI_ADMIN_GROUP
from OPSI.Exceptions import BackendMissingDataError
from OPSI.Util import deserialize, getPublicKey
from OPSI.Object import NetbootProduct, Host
from OPSI.Types import forceHostId, forceUnicodeList

from .logging import init_logging
from .util import StartupTask, ClientConnection
from .pxeconfigwriter import PXEConfigWriter

ELILO_X86 = "x86"
ELILO_X64 = "x64"


class Opsipxeconfd(threading.Thread):  # pylint: disable=too-many-instance-attributes
	"""
	class Opsipxeconfd

	This class handles installation of NetbootProducts via network.
	"""

	def __init__(self, config: Dict) -> None:
		"""
		Opsipxeconfd constructor.

		This constructor initializes a new Opsipxeconfd instance.
		Settings are set according to the proveded config dictionary.

		:param config: Opsipxeconfd configuration dictionary as loaded from file
			or specified on command line at execution time.
		:type config: Dict
		"""
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
		self._secureBootModule = False
		self._uefiModule = False

		logger.comment("opsi pxe configuration service starting")

	def setConfig(self, config: Dict) -> None:
		"""
		Sets new configuration.

		This method expects a configuration dictionary and overrides
		the existing configuration with the new one.

		:param config: Opsipxeconfd configuration dictionary.
		:type config: Dict
		"""
		logger.notice("Got new config")
		self.config = config

	def isRunning(self) -> bool:
		"""
		Execution status request.

		This method returns whether this instance of Opsipxeconfd is running.

		:returns: True if Opsipxeconfd is running, else False.
		:rtype: bool
		"""
		return self._running

	def stop(self) -> None:
		"""
		Request to stop Opsipxeconfd thread.

		This method requests a stop and join for the associated
		StartupTask instance. Afterwards it requests a stop
		for the current Opsipxeconfd thread.
		"""
		logger.notice("Stopping opsipxeconfd main thread")

		try:
			self._startupTask.stop()
			self._startupTask.join(10)
		except AttributeError:
			pass  # Probably still set to None.
		except RuntimeError:
			pass  # Probably not yet started
		except Exception as err:  # pylint: disable=broad-except
			logger.debug("Unhandled error during stop: '%s", err)

		self._running = False

		try:
			self._socket.close()
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to close socket: %s", err)

	def reload(self) -> None:
		"""
		Reloads the Opsipxeconfd config.

		This method reinitializes logging for the
		(possibly altered) configuration dictionary.
		Then recreates the backend and the socket.
		"""
		logger.notice("Reloading opsipxeconfd")
		init_logging(self.config)
		self._createBackendInstance()
		self._createSocket()

	def _createBackendInstance(self) -> None:
		"""
		Creates BackendManager instance.

		This method creates a new BackendManager instance and stores it.
		To configure the BackendManager, the dispatchConfig and the
		backendConfig are read.
		"""
		logger.info("Creating backend instance")
		self._backend = BackendManager(
			dispatchConfigFile=self.config["dispatchConfigFile"],
			dispatchIgnoreModules=["OpsiPXEConfd"],  # Avoid loops
			backendConfigDir=self.config["backendConfigDir"],
			extend=True,
		)
		self._backend.backend_setOptions({"addProductPropertyStateDefaults": True, "addConfigStateDefaults": True})

	def _createSocket(self) -> None:
		"""
		Creates new Socket.

		This method instantiates a new UnixSocket and binds it to a file
		specified in config['port']. Theoretically this UnixSocket could
		be substituted by a network socket bound to a network port.
		"""
		self._createUnixSocket()

	def _createUnixSocket(self) -> None:
		"""
		Creates new UnixSocket.

		This method instantiates a new UnixSocket and binds it to a file
		specified in config['port']. Access rights are adjusted for the
		resulting socket file.
		"""
		logger.notice("Creating unix socket %s", self.config["port"])
		if os.path.exists(self.config["port"]):
			os.unlink(self.config["port"])
		self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		try:
			self._socket.bind(self.config["port"])
		except Exception as err:
			raise Exception(f"Failed to bind to socket '{self.config['port']}': {err}") from err
		self._socket.settimeout(0.1)
		self._socket.listen(self.config["maxConnections"])

		self._setAccessRightsForSocket(self.config["port"])

	def _setAccessRightsForSocket(self, path: str) -> None:
		"""
		Sets access rights for UnixSocket.

		This method adjusts the permissions of a UnixSocket file to o*66
		and gives group ownership to opsiadmin group.

		:param path: Path of the UnixSocket.
		:type path: str
		"""
		logger.debug("Setting rights on socket '%s'", path)
		mode = os.stat(path)[0]
		# Adding read + write access for group and other.
		os.chmod(path, mode | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
		os.chown(path, -1, self._opsi_admin_gid)
		logger.debug("Done setting rights on socket '%s'", path)

	def _getConnection(self) -> None:
		"""
		Creates and starts ClientConnection thread.

		This method initializes a ClientConnection thread, passing
		the associated socket and clientConnectionCallback.
		Afterwards, the ClientConnection is run.
		"""
		try:
			sock, _ = self._socket.accept()
		except socket.error as err:
			if not self._running:
				return
			if err.args[0] == "timed out" or err.args[0] == 11:
				return

			logger.debug("Socket error: %s", err)
			raise err
		logger.notice("Got connection from client")

		cc = None
		logger.info("Creating thread for connection %d", len(self._clientConnections) + 1)
		try:
			cc = ClientConnection(self, sock, self.clientConnectionCallback)
			with self._clientConnectionLock:
				self._clientConnections.append(cc)
			cc.start()
			logger.debug("Connection %s started.", cc.name)
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to create control connection: %s", err, exc_info=True)

			with self._clientConnectionLock:
				try:
					self._clientConnections.remove(cc)
				except ValueError:
					pass  # Element not in list

	def run(self) -> None:
		"""
		Opsipxeconfd thread main method.

		This method is run on Opsipxeconfd execution.
		It creates backend, StartupTask and socket.
		"""
		with log_context({"instance": "Opsipxeconfd"}):
			self._running = True
			logger.notice("Starting opsipxeconfd main thread")
			try:
				self._createBackendInstance()
				logger.info("Setting needed boot configurations")
				self._startupTask = StartupTask(self)
				self._startupTask.start()
				self._createSocket()
				while self._running:
					self._getConnection()
				logger.notice("Opsipxeconfd main thread exiting...")
			except Exception as err:  # pylint: disable=broad-except
				logger.error(err, exc_info=True)
			finally:
				self._running = False

	def clientConnectionCallback(self, connection: ClientConnection) -> None:
		"""
		Callback method for ClientConnection.

		This method is meant to be hooked to ClientConnection instances.
		Upon end of their run method, this is called.
		It logs the time of life of the Clientconnection and removes the
		ClientConnection instance, so that it can be garbage collected.

		:param connection: ClientConnection that the callback is hooked to.
		:type connection: ClientConnection
		"""
		logger.info("ClientConnection %s finished (took %0.3f seconds)", connection.name, (time.time() - connection.startTime))

		try:
			with self._clientConnectionLock:
				try:
					self._clientConnections.remove(connection)
				except ValueError:
					pass  # Connection not in list

			logger.debug("ClientConnection '%s' removed", connection.name)
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to remove ClientConnection: %s", err)

	def pxeConfigWriterCallback(self, pcw: PXEConfigWriter) -> None:
		"""
		Callback for PXEConfigWriter

		This method is hooked to a PXEConfigWriter instance.
		It is run at the end of PXEConfigWriter thread execution.
		The PXEConfigWriter is removed from the Opsipxeconfd instance
		and backend and pxebootconfiguration are updated.

		:param pcw: PXEConfigWriter this method should be hooked to.
		:type pcw: PXEConfigWriter
		"""
		logger.info("PXEConfigWriter %s (for %s) finished (running for %0.3f seconds)", pcw.name, pcw.hostId, (time.time() - pcw.startTime))

		try:
			with self._pxeConfigWritersLock:
				try:
					self._pxeConfigWriters.remove(pcw)
				except ValueError:
					pass  # Writer not in list
			logger.debug("PXE config writer removed")
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to remove PXE config writer: %s", err)

		gotAlways = False
		for i, poc in enumerate(pcw.productOnClients):
			# renew objects and check if anythin changes on service since callback
			productOnClients = self._backend.productOnClient_getObjects(  # pylint: disable=no-member
				productType="NetbootProduct", clientId=poc.clientId, productId=poc.productId
			)
			if productOnClients:
				pcw.productOnClients[i] = productOnClients[0]
			else:
				del pcw.productOnClients[i]

			if pcw.productOnClients:
				pcw.productOnClients[i].setActionProgress("pxe boot configuration read")
				if pcw.productOnClients[i].getActionRequest() == "always":
					gotAlways = True
				if pcw.templatefile != self.config["pxeConfTemplate"] and not gotAlways:
					pcw.productOnClients[i].setActionRequest("none")

		if pcw.productOnClients:
			self._backend.productOnClient_updateObjects(pcw.productOnClients)  # pylint: disable=no-member
		if gotAlways:
			self.updateBootConfiguration(pcw.hostId)

	def status(self) -> str:
		"""
		Returns status information.

		This method collects status information about a running
		Opsipxeconfd instance. The result is returned as a string.

		:returns: Status information about running Opsipxeconfd.
		:rtype: str
		"""
		logger.notice("Getting opsipxeconfd status")
		result = "opsipxeconfd status:\n"

		with self._clientConnectionLock:
			result += f"{len(self._clientConnections)} control connection(s) established\n"
			for idx, connection in enumerate(self._clientConnections, start=1):
				result += f"    Connection {idx} established at: {time.asctime(time.localtime(connection.startTime))}\n"

		result += f"\n{len(self._pxeConfigWriters)} boot configuration(s) set\n"
		for pcw in self._pxeConfigWriters:
			result += (
				f"Boot config for client '{pcw.hostId}' (path '{pcw.pxefile}'; configuration {pcw.append}) "
				f"set since {time.asctime(time.localtime(pcw.startTime))}\n"
			)
		logger.notice(result)
		return result

	def _check_modules_legacy(self, cached_data: dict):  # pylint: disable=too-many-branches
		try:
			backend_info = cached_data["backendInfo"]
		except KeyError:
			backend_info = self._backend.backend_info()

		modules = backend_info["modules"]
		helpermodules = backend_info["realmodules"]
		public_key = getPublicKey(
			data=base64.decodebytes(
				b"AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDo"
				b"jY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8"
				b"S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDU"
				b"lk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP"
			)
		)
		data = ""
		mks = list(modules.keys())
		mks.sort()
		for module in mks:
			if module in ("valid", "signature"):
				continue
			if module in helpermodules:
				val = helpermodules[module]
				if int(val) > 0:
					modules[module] = True
			else:
				val = modules[module]
				if isinstance(val, bool):
					val = "yes" if val else "no"
			data += f"{module.lower().strip()} = {val}\r\n"

		verified = False
		if modules["signature"].startswith("{"):
			s_bytes = int(modules["signature"].split("}", 1)[-1]).to_bytes(256, "big")
			try:
				pkcs1_15.new(public_key).verify(MD5.new(data.encode()), s_bytes)
				verified = True
			except ValueError:
				# Invalid signature
				pass
		else:
			h_int = int.from_bytes(MD5.new(data.encode()).digest(), "big")
			s_int = public_key._encrypt(int(modules["signature"]))  # pylint: disable=protected-access
			verified = h_int == s_int

		if not verified:
			logger.error("Modules file invalid.")
			self._uefiModule = False
			self._secureBootModule = False
			return

		logger.debug("Modules file signature verified (customer: %s)", modules.get("customer"))

		if modules.get("uefi"):
			num_clients = len(self._backend.host_getIdents(type="OpsiClient"))  # pylint: disable=no-member
			if int(modules["uefi"]) + 50 <= num_clients:
				logger.error("You have more clients then licensed in modules file. Disabling module 'uefi'")
			else:
				self._uefiModule = True
				if int(modules["uefi"]) <= num_clients:
					logger.warning("You have more clients then licensed in modules file.")

		if modules.get("secureboot"):
			self._secureBootModule = True

	def _check_modules(self, cached_data: dict):  # pylint: disable=too-many-branches
		if not hasattr(self._backend, "backend_getLicensingInfo"):
			self._check_modules_legacy(cached_data)
		else:
			info = self._backend.backend_getLicensingInfo(licenses=False, legacy_modules=False, dates=False, allow_cache=True)  # pylint: disable=no-member
			logger.debug("Got licensing info from service: %s", info)
			if "uefi" in info["available_modules"]:
				self._uefiModule = True
			if "secureboot" in info["available_modules"]:
				self._secureBootModule = True
		logger.info(
			"uefi module is %s, secureboot module is %s",
			"enabled" if self._uefiModule else "disabled",
			"enabled" if self._secureBootModule else "disabled",
		)

	def updateBootConfiguration(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements,inconsistent-return-statements
		self, hostId: str, cacheFile: str = None
	) -> None:
		"""
		Updates Boot Configuration.

		This method is called for a specific host. It updates the PXE boot
		configuration for it. For NetbootProducts with pending action requests,
		a PXEConfigWriter is created and run.

		:param hostId: fqdn of a host in the network.
		:type hostId: str
		:param cacheFile: Path of a cache file (optional)
		:type cacheFile: str
		"""
		try:
			hostId = forceHostId(hostId)
			logger.info("Updating PXE boot configuration for host '%s'", hostId)

			self._removeCurrentConfigWriters(hostId)

			cachedData = self._readCachedData(cacheFile)
			if cachedData:
				logger.debug("Cached data read for %s: '%s'", hostId, cachedData)

			try:
				poc = cachedData["productOnClient"]
				if poc:
					productOnClients = [poc]
				else:
					productOnClients = None
			except KeyError:
				# Get product actions
				productOnClients = self._backend.productOnClient_getObjects(  # pylint: disable=no-member
					productType="NetbootProduct",
					clientId=hostId,
					actionRequest=["setup", "uninstall", "update", "always", "once", "custom"],
				)

			if not productOnClients:
				logger.info("No netboot products with action requests for client '%s' found.", hostId)
				return "Boot configuration updated"

			try:
				host = cachedData["host"]
			except KeyError:
				host = self._getHostObject(hostId)

			depotId = self.config["depotId"]

			newProductOnClients = []
			for poc in productOnClients:
				try:
					productOnDepot = cachedData["productOnDepot"]
				except KeyError:
					logger.debug("Searching for product '%s' on depot '%s'", poc.productId, depotId)
					productOnDepot = self._backend.productOnDepot_getObjects(  # pylint: disable=no-member
						productType="NetbootProduct", productId=poc.productId, depotId=depotId
					)

					try:
						productOnDepot = productOnDepot[0]
					except IndexError:
						logger.info("Product %s not available on depot '%s'", poc.productId, depotId)
						continue

				if productOnDepot:
					poc.productVersion = productOnDepot.productVersion
					poc.packageVersion = productOnDepot.packageVersion
					newProductOnClients.append(poc)

			productOnClients = newProductOnClients

			if not productOnClients:
				logger.info("No matching netboot product found on depot '%s'.", depotId)
				return "Boot configuration updated"

			try:
				product = cachedData["product"]

				# Setting empty string to avoid making another
				# unnecessary call to the backend.
				elilo = cachedData["elilo"] or ""
			except KeyError:
				product = None
				elilo = None
				self._backend.backend_setOptions({"addProductPropertyStateDefaults": True, "addConfigStateDefaults": True})

			pxeConfigTemplate, product = self._getPxeConfigTemplate(hostId, productOnClients, product, elilo)
			logger.debug("Using pxe config template '%s'", pxeConfigTemplate)

			pxeConfigName = self._getNameForPXEConfigFile(host)

			pxefile = os.path.join(self.config["pxeDir"], pxeConfigName)
			if os.path.exists(pxefile):
				for pcw in self._pxeConfigWriters:
					if pcw.uefi and not pcw._uefiModule:  # pylint: disable=protected-access
						raise Exception("Should use uefi netboot, but uefi module is not licensed.")
					if pcw.pxefile == pxefile:
						if host.id == pcw.hostId:
							logger.notice("PXE boot configuration '%s' for client '%s' already exists.", pxefile, host.id)
							return
						raise Exception(
							f"PXE boot configuration '{pxefile}' already exists. Clients '{host.id}' and '{pcw.hostId}' using same address?"
						)
				logger.debug("PXE boot configuration '%s' already exists, removing.", pxefile)
				os.unlink(pxefile)

			try:
				serviceAddress = cachedData["serviceAddress"]
			except KeyError:
				serviceAddress = self._getConfigServiceAddress(hostId)

			# Append arguments
			append = {
				"pckey": host.getOpsiHostKey(),
				"hn": hostId.split(".")[0],
				"dn": ".".join(hostId.split(".")[1:]),
				"product": product.id,
				"macaddress": host.getMacAddress(),
				"service": serviceAddress,
			}
			if append["pckey"]:
				secret_filter.add_secrets(append["pckey"])

			try:
				bootimageAppendConfigStates = [cachedData["bootimageAppend"]]
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
						pps.propertyId: ",".join(forceUnicodeList(pps.getValues()))
						for pps in self._backend.productPropertyState_getObjects(  # pylint: disable=no-member
							objectId=hostId, productId=productIds
						)
					}
				else:
					productPropertyStates = {}

			pcw = None
			try:
				logger.info("Creating thread for pxeconfig %d", len(self._pxeConfigWriters) + 1)
				self._check_modules(cachedData)
				pcw = PXEConfigWriter(
					templatefile=pxeConfigTemplate,
					hostId=hostId,
					productOnClients=productOnClients,
					append=append,
					productPropertyStates=productPropertyStates,
					pxefile=pxefile,
					secureBootModule=self._secureBootModule,
					uefiModule=self._uefiModule,
					callback=self.pxeConfigWriterCallback,
				)
				with self._pxeConfigWritersLock:
					self._pxeConfigWriters.append(pcw)
				pcw.start()
				logger.notice("PXE boot configuration for host %s is now set at '%s'", hostId, pxefile)
				return "Boot configuration updated"
			except Exception as err:
				logger.error("Failed to create pxe config writer: %s", err)

				with self._pxeConfigWritersLock:
					try:
						self._pxeConfigWriters.remove(pcw)
					except ValueError:
						pass  # Writer not in list

				raise
		except Exception as err:
			logger.error(err, exc_info=True)
			raise err

	def _removeCurrentConfigWriters(self, hostId: str) -> None:
		"""
		Remove PXEConfigWriters for host.

		This method removes all registered PXEConfigWriters that are registered
		for a given host.

		:param hostId: fqdn of the host for which PXEConfigWriters should be removed.
		:type hostId: str
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

			logger.notice("PXE boot configuration for host '%s' removed", hostId)

	@staticmethod
	def _readCachedData(cacheFile: str) -> Any:
		"""
		Reads data from cache.

		This method loads contents of a cache file and parses them
		as json. The result is deserialized and returned as either List or Dict.

		:param cacheFile: Path of a cache file (optional)
		:type cacheFile: str

		:returns: deserialized cache content as List or Dict.
		:rtype: Any
		"""
		if not cacheFile or not os.path.exists(cacheFile):
			return {}

		logger.debug("Reading data from %s", cacheFile)
		with codecs.open(cacheFile, "r", "utf-8") as inFile:
			data = json.load(inFile)
		os.unlink(cacheFile)

		return deserialize(data)

	def _getHostObject(self, hostId: str) -> Any:
		"""
		Get the object for `hostId`.

		This method requests a host object from backend, stored
		under given hostId.

		:param hostId: fqdn of host.
		:type hostId: str

		:returns: Host instance requested with hostId.
		:rtype: Any

		:raises ValueError: In case the given host is not found.
		"""
		logger.debug("Searching for host with id '%s'", hostId)

		host = self._backend.host_getObjects(id=hostId)  # pylint: disable=no-member
		try:
			return host[0]
		except IndexError as err:
			raise ValueError(f"Host '{hostId}' not found") from err

	def _getPxeConfigTemplate(  # pylint: disable=too-many-branches
		self, hostId: str, productOnClients: List, product: NetbootProduct = None, elilo: str = None
	) -> Tuple:
		"""
		Get pxe template to use for `hostId`.

		This method determines the pxe template file that should be used for a client
		specified by fqdn in hostId. This depends on the architecture and the type
		of NetbootProduct and action request.

		:param hostId: fqdn of host.
		:type hostId: str
		:param productOnClients: list of Products on Clients.
		:type productOnClients: List
		:param product: Product to check for.
		:type product: NetbootProduct
		:param elilo: Type of architecture (x64 or x86)
		:type elilo: str

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
					product = self._backend.product_getObjects(  # pylint: disable=no-member
						type="NetbootProduct", id=poc.productId, productVersion=poc.productVersion, packageVersion=poc.packageVersion
					)[0]
				except IndexError:
					product = None

			if not product:
				raise BackendMissingDataError(f"Product not found: {poc.productId}_{poc.productVersion}-{poc.packageVersion}")

			if ELILO_X86 == elilo:
				pxeConfigTemplate = self.config["uefiConfTemplateX86"]
			elif ELILO_X64 == elilo:
				pxeConfigTemplate = self.config["uefiConfTemplateX64"]

			if product.pxeConfigTemplate:
				if pxeConfigTemplate and (pxeConfigTemplate != product.pxeConfigTemplate):
					logger.error("Cannot use more than one pxe config template, got: %s, %s", pxeConfigTemplate, product.pxeConfigTemplate)
					absolutePathToTemplate = os.path.join(os.path.dirname(self.config["pxeConfTemplate"]), product.pxeConfigTemplate)
					if os.path.isfile(f"{absolutePathToTemplate}.efi"):
						logger.notice("Using an alternate UEFI template provided by netboot product")
						pxeConfigTemplate = f"{product.pxeConfigTemplate}.efi"
					else:
						logger.notice("Did not find any alternate UEFI pxeConfigTemplate, will use the default UEFI template")

				else:
					pxeConfigTemplate = product.pxeConfigTemplate
					logger.notice(
						"Special pxe config template '%s' will be used used for host '%s', product '%s'",
						pxeConfigTemplate,
						hostId,
						poc.productId,
					)

		if not pxeConfigTemplate:
			logger.debug("Using default config template")
			pxeConfigTemplate = self.config["pxeConfTemplate"]

		if not os.path.isabs(pxeConfigTemplate):  # Not an absolute path
			logger.debug("pxeConfigTemplate is not an absolute path.")
			pxeConfigTemplate = os.path.join(os.path.dirname(self.config["pxeConfTemplate"]), pxeConfigTemplate)
			logger.debug("pxeConfigTemplate changed to %s", pxeConfigTemplate)

		return pxeConfigTemplate, product

	def _detectEliloMode(self, hostId: str) -> str:
		"""
				Checks if elilo mode is set for client.

				This method searches the backend configStates for the host for
				hints regarding the system architecture. It returns the elilo mode as string.

				:param hostId: fqdn of the client.
				:type hostId: str

				:rtype: str or None
				:returns: The elilo mode of the client represented as either
		`x86` or `x64` if it is set. If no elilo mode is set then `None`.
		"""
		eliloMode = None
		configStates = self._backend.configState_getObjects(  # pylint: disable=no-member
			configId="clientconfig.dhcpd.filename", objectId=hostId
		)
		if configStates:
			val = configStates[0].getValues()
			if val and (("elilo" in val[0]) or ("shimx64" in val[0])):
				if "x86" in val[0]:
					eliloMode = ELILO_X86
				else:
					eliloMode = ELILO_X64

		return eliloMode

	@staticmethod
	def _getNameForPXEConfigFile(host: Host) -> str:
		"""
		Gets network address information.

		This method requests the ipv4 and the hardware address of
		a host and returns it as string.

		:param host: Host instance to get network address information from.
		:type host: Host

		:returns: String containing network address information of the host.
		:rtype: str
		"""
		if host.getHardwareAddress():
			logger.debug("Got hardware address '%s' for host '%s'", host.getHardwareAddress(), host.id)
			return f"01-{host.getHardwareAddress().replace(':', '-')}"
		if host.getIpAddress():
			logger.warning("Failed to get hardware address for host '%s', using ip address '%s'", host.id, host.getIpAddress())
			return "%02X%02X%02X%02X" % tuple(  # pylint: disable=consider-using-generator,consider-using-f-string
				[int(i) for i in host.getIpAddress().split(".")]
			)
		raise Exception(f"Neither hardware address nor ip address known for host '{host.id}'")

	def _getConfigServiceAddress(self, hostId: str) -> str:
		"""
		Returns the config serive address for `hostId`.

		This method requests the url of the configserver, ensures
		that it ends with /rpc and returns it as a string.

		:param hostId: fqdn of client.
		:type hostId: str

		:returns: url of the configserver.
		:rtype: str
		"""
		address = ""

		configStates = self._backend.configState_getObjects(  # pylint: disable=no-member
			objectId=hostId, configId="clientconfig.configserver.url"
		)
		if configStates:
			address = configStates[0].getValues()[0]

		if not address.endswith("/rpc"):
			address += "/rpc"

		return address

	def _getAdditionalBootimageParameters(self, hostId: str, configStates: List = None) -> Tuple:
		"""
		Returns additional bootimage parameters.

		This method requests additional bootimage parameters set for hostId
		and yields them (generator!).

		:param hostId: fqdn of client.
		:type hostId: str
		:param configStates: Config States of hostId as List (optional).
		:type configStates: List
		:returns: key-value pairs as tuple (value possibly empty) as yield.
		:rtype: Tuple
		"""
		if configStates is None:
			configStates = self._backend.configState_getObjects(  # pylint: disable=no-member
				objectId=hostId, configId="opsi-linux-bootimage.append"
			)

		if configStates:
			app = " ".join(forceUnicodeList(configStates[0].getValues()))
			for option in app.split():
				keyValue = option.split("=")
				if len(keyValue) < 2:
					yield keyValue[0].strip().lower(), ""
				else:
					yield keyValue[0].strip().lower(), keyValue[1].strip()
