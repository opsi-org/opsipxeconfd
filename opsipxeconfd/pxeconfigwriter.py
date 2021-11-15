# -*- coding: utf-8 -*-

# opsipxeconfd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2013-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

"""
pxeconfigwriter
"""

import os
import time
import threading
from typing import List, Dict, Callable

from opsicommon.logging import logger, log_context

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
		secureBootModule: bool,
		uefiModule: bool,
		callback: Callable=None
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
		self._secureBootModule = bool(secureBootModule)
		self._uefiModule = bool(uefiModule)
		self._callback = callback
		self.startTime = time.time()
		self._running = False
		self._pipe = None
		self.uefi = False
		self._usingGrub = False

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
		with log_context({'instance' : 'PXEConfigWriter'}):
			self._running = True
			try:
				self._run()
			except Exception as err: # pylint: disable=broad-except
				logger.error(err, exc_info=True)
			self._running = False

	def _run(self) -> None:
		"""
		PXEConfigWriter main method.

		This method opens a pipe and sends the PXE boot configuration through
		that pipe. At the end the hooked callback is executed.
		"""
		if os.path.exists(self.pxefile):
			logger.info("Removing existing file '%s'", self.pxefile)
			os.unlink(self.pxefile)

		pipeOpenend = False
		while self._running and not pipeOpenend:
			try:
				if not os.path.exists(self.pxefile):
					os.mkfifo(self.pxefile, mode=0o644)
				self._pipe = os.open(self.pxefile, os.O_WRONLY | os.O_NONBLOCK)
				pipeOpenend = True
			except OSError as err:
				if err.errno != 6:  # pylint: disable=no-member
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
