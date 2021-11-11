# -*- coding: utf-8 -*-

# opsipxeconfd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2013-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

"""
pxeconfigwriter
"""

import threading
import time
import base64
import os
from typing import List, Dict, Callable
from hashlib import md5

try:
	# python3-pycryptodome installs into Cryptodome
	from Cryptodome.Hash import MD5 # type: ignore
	from Cryptodome.Signature import pkcs1_15 # type: ignore
except ImportError:
	# PyCryptodome from pypi installs into Crypto
	from Crypto.Hash import MD5
	from Crypto.Signature import pkcs1_15

from opsicommon.logging import logger, log_context
from OPSI.Util import getPublicKey

class PXEConfigWriter(threading.Thread):  # pylint: disable=too-many-instance-attributes
	"""
	class PXEConfigWriter

	This class handles the sending of PXE boot information to clients.
	"""
	def __init__(  # pylint: disable=too-many-arguments,too-many-locals,too-many-branches,too-many-statements
		self,
		templatefile: str,
		hostId: str,
		productOnClients: List,
		append: Dict,
		productPropertyStates: Dict,
		pxefile: str,
		callback: Callable=None,
		backendinfo: Dict=None
	) -> None:
		"""
		PXEConfigWriter constructor.

		This constructor initializes a new PXEConfigWriter thread.
		Template- and PXE-file paths as well as, hostID, products and their states
		are stored.

		:param templatefile: Path of the PXE template file.
		:type templatefile: str
		:param hostId: fqdn of client.
		:type hostId:str
		:param productOnClients: List of Products on Clients.
		:type productOnClients: List
		:param append: Dictionary of additional Information (pckey).
		:type append: Dict
		:param productPropertyStates: Data to be collected by _getPXEConfigContent.
		:type productPropertyStates: Dict
		:param pxefile: Path of the PXEfile.
		:type pxefile: str
		:param callback: Optional Callback (executed after running PXEConfigWriter).
		:type callback: Callable
		:param backendinfo: Dictionary with information about the backend.
				This data is parsed for uifi module license at init.
		:type backendinfo: Dict
		"""
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

		# backendinfo: expect this to be a dict
		if backendinfo:  # pylint: disable=too-many-nested-blocks
			modules = backendinfo['modules']
			helpermodules = backendinfo['realmodules']
			hostCount = backendinfo['hostCount']

			if modules.get('customer'):
				logger.info("Verifying modules file signature")
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
						if module == 'uefi':
							if int(val) + 50 <= hostCount:
								logger.error("UNDERLICENSED: You have more Clients then licensed in modules file. Disabling module: '%s'", module)
								modules[module] = False
							elif int(val) <= hostCount:
								logger.warning("UNDERLICENSED WARNING: You have more Clients then licensed in modules file.")
						else:
							if int(val) > 0:
								modules[module] = True
					else:
						val = modules[module]
						if isinstance(val, bool):
							val = "yes" if val else "no"
					data += f"{module.lower().strip()} = {val}\r\n"

				verified = False
				if modules["signature"].startswith("{"):
					s_bytes = int(modules['signature'].split("}", 1)[-1]).to_bytes(256, "big")
					try:
						pkcs1_15.new(public_key).verify(MD5.new(data.encode()), s_bytes)
						verified = True
					except ValueError:
						# Invalid signature
						pass
				else:
					h_int = int.from_bytes(md5(data.encode()).digest(), "big")
					s_int = public_key._encrypt(int(modules["signature"]))
					verified = h_int == s_int

				if not verified:
					logger.error("Failed to verify modules signature")
					return

				logger.debug("Modules file signature verified (customer: %s)", modules.get('customer'))

				if modules.get('uefi'):
					self._uefiModule = True
				if modules.get('secureboot'):
					self._secureBootModule = True

		logger.info("PXEConfigWriter initializing: templatefile '%s', pxefile '%s', hostId '%s', append %s",
					self.templatefile, self.pxefile, self.hostId, self.append)

		if not os.path.exists(self.templatefile):
			raise Exception(f"Template file '{self.templatefile}' not found")

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

	def _getPXEConfigContent(self, templateFile : str) -> str:  # pylint: disable=too-many-branches
		"""
		Gets PXEConfig string.

		This method extracts information about the PXEConfig from the
		template file, parses it using information from the
		productPropertyStates and assemples the data as a string.

		:param templateFile: Path of the PXE template file.
		:type templateFile: str

		:returns: PXE configuration information as string.
		:rtype: str

		:raises Exception: In case uefi module is not licensed.
		"""
		logger.debug("Reading template '%s'", templateFile)
		with open(templateFile, 'r', encoding="utf-8") as file:
			templateLines = file.readlines()

		content = ''
		appendLineProperties = []
		for line in templateLines:
			line = line.rstrip()

			for (propertyId, value) in self.productPropertyStates.items():
				logger.trace("Property: '%s': value: '%s'", propertyId, value)
				line = line.replace(f'%{propertyId}%', value)

			if line.lstrip().startswith('append'):
				if line.lstrip().startswith('append='):
					logger.notice("elilo configuration detected for %s", self.hostId)
					self.uefi = True
					appendLineProperties = ''.join(line.split('="')[1:])[:-1].split()
				else:
					self.uefi = False
					appendLineProperties = line.lstrip().split()[1:]

				for key, value in self.append.items():
					if value:
						appendLineProperties.append(f"{key}={value}")
					else:
						appendLineProperties.append(str(key))

				if self._uefiModule and self.uefi:
					content = f'{content}append="{" ".join(appendLineProperties)}"\n'
				elif not self._uefiModule and self.uefi:
					raise Exception("You have not licensed uefi module, please check your modules or contact info@uib.de")
				else:
					content = f'{content}  append {" ".join(appendLineProperties)}\n'
			elif line.lstrip().startswith('linux'):
				logger.notice("UEFI GRUB configuration detected for %s", self.hostId)
				if not self._uefiModule and self.uefi:
					raise Exception("You have not licensed uefi module, please check your modules or contact info@uib.de")

				self.uefi = True
				self._usingGrub = True
				appendLineProperties = line.lstrip().split()[1:]
				for key, value in self.append.items():
					if value:
						appendLineProperties.append(f"{key}={value}")
					else:
						appendLineProperties.append(str(key))

				content = f'{content}linux {" ".join(appendLineProperties)}\n'
			else:
				content = f"{content}{line}\n"

		return content

	def run(self) -> None:
		"""
		PXEConfigWriter main method.

		This method opens a pipe and sends the PXE boot configuration through
		that pipe. At the end the hooked callback is executed.
		"""
		with log_context({'instance' : 'PXEConfigWriter'}):
			self._running = True
			pipeOpenend = False
			while self._running and not pipeOpenend:
				try:
					self._pipe = os.open(self.pxefile, os.O_WRONLY | os.O_NONBLOCK)
					pipeOpenend = True
				except Exception as err:  # pylint: disable=broad-except
					if hasattr(err, "errno") or err.errno != 6:  # pylint: disable=no-member
						raise
					time.sleep(1)

			if pipeOpenend:
				logger.notice("Pipe '%s' opened, piping pxe boot configuration", self.pxefile)
				os.write(self._pipe, self.content.encode())
				if self.uefi and self._usingGrub:
					time.sleep(5)
				os.close(self._pipe)

			if os.path.exists(self.pxefile):
				os.unlink(self.pxefile)

			if pipeOpenend and self._callback:
				self._callback(self)

	def stop(self):
		"""
		Stop PXEConfigWriter thread.

		This method requests a stop for the current PXEConfigWriter instance.
		"""
		self._running = False
