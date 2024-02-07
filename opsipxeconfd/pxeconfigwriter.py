# -*- coding: utf-8 -*-

# opsipxeconfd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2013-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

"""
pxeconfigwriter
"""

import os
import shutil
import time
from threading import Event, Thread
from typing import Callable

from inotify.adapters import Inotify  # type: ignore[import]
from opsicommon.config.opsi import OpsiConfig
from opsicommon.logging import get_logger, log_context
from opsicommon.objects import ProductOnClient

from opsipxeconfd.setup import encode_password

logger = get_logger()
opsi_config = OpsiConfig()


class PXEConfigWriter(Thread):  # pylint: disable=too-many-instance-attributes
	"""
	class PXEConfigWriter

	This class handles the sending of PXE boot information to clients.
	"""

	def __init__(  # pylint: disable=too-many-arguments,too-many-locals,too-many-branches,too-many-statements
		self,
		template_file: str,
		host_id: str,
		product_on_client: ProductOnClient,
		append: dict,
		product_property_states: dict,
		pxefiles: list[str],
		secure_boot_module: bool,
		uefi_module: bool,
		callback: Callable | None = None,
	) -> None:
		"""
		PXEConfigWriter constructor.

		This constructor initializes a new PXEConfigWriter thread.
		Template- and PXE-file paths as well as, hostID, products and their states
		are stored.

		:param template_file: Path of the PXE template file.
		:type template_file: str
		:param host_id: fqdn of client.
		:type host_id:str
		:param product_on_client: ProductOnClient.
		:type product_on_client: ProductOnClient
		:param append: dictionary of additional Information (pckey).
		:type append: dict
		:param productPropertyStates: Data to be collected by _getPXEConfigContent.
		:type productPropertyStates: dict
		:param pxefiles: Path of the PXEfiles.
		:type pxefile: list[str]
		:param callback: Optional Callback (executed after running PXEConfigWriter).
		:type callback: Callable
		:param backendinfo: dictionary with information about the backend.
		                This data is parsed for uifi module license at init.
		:type backendinfo: dict
		"""
		Thread.__init__(self)
		self.daemon = True
		self.template_file = template_file
		self.append = append
		self.product_property_states = product_property_states
		self.host_id = host_id
		self.product_on_client = product_on_client
		self.pxefiles = pxefiles
		self._secure_boot_module = bool(secure_boot_module)
		self._uefi_module = bool(uefi_module)
		self._callback = callback
		self.start_time = time.time()
		self._running = False
		self._should_stop = False
		self.stopped_event = Event()

		logger.info(
			"PXEConfigWriter initializing: template_file '%s', pxefiles %s, host_id '%s', append %s",
			self.template_file,
			self.pxefiles,
			self.host_id,
			self.append,
		)

		if not os.path.exists(self.template_file):
			raise FileNotFoundError(f"Template file '{self.template_file}' not found")

		self.template: dict[str, list[str]] = {"pxelinux": []}

		# Set pxe config content
		self.content = self._get_pxe_config_content(self.template_file)

		try:
			del self.append["pckey"]
		except KeyError:
			pass  # Key may be non-existing

	def _get_pxe_config_content(self, template_file: str) -> str:  # pylint: disable=too-many-branches,too-many-statements
		"""
		Gets PXEConfig string.

		This method extracts information about the PXEConfig from the
		template file, parses it using information from the
		productPropertyStates and assemples the data as a string.

		:param template_file: Path of the PXE template file.
		:type template_file: str

		:returns: PXE configuration information as string.
		:rtype: str

		:raises Exception: In case uefi module is not licensed.
		"""
		logger.debug("Reading template '%s'", template_file)
		with open(template_file, "r", encoding="utf-8") as file:
			template_lines = file.readlines()

		content = ""
		append_line_properties = []
		for line in template_lines:
			line = line.rstrip()

			for property_id, value in self.product_property_states.items():
				logger.trace("Property: '%s': value: '%s'", property_id, value)
				line = line.replace(f"%{property_id}%", value)

			if line.lstrip().startswith(("append", "linux")):
				if line.lstrip().startswith("append"):
					append_line_properties = "".join(line.split('="')[1:])[:-1].split()
				else:
					append_line_properties = line.lstrip().split()[1:]

				for key, value in self.append.items():
					if value:
						if "bootimagerootpassword" in key.lower():
							pwhash = encode_password(value).replace("$", r"\$")
							append_line_properties.append(f"pwh={pwhash}")
						elif "pwh" in key.lower():
							pwhash = value.replace("$", r"\$")
							append_line_properties.append(f"{key}={pwhash}")
						else:
							append_line_properties.append(f"{key}={value}")
					else:
						append_line_properties.append(str(key))

				if line.lstrip().startswith("append"):
					content = f'{content}append="{" ".join(append_line_properties)}"\n'
				else:
					content = f'{content}linux {" ".join(append_line_properties)}\n'
			else:
				content = f"{content}{line}\n"

		return content

	def run(self) -> None:
		with log_context({"instance": "PXEConfigWriter"}):
			self._running = True
			try:
				self._run()
			except Exception as err:  # pylint: disable=broad-except
				logger.error(err, exc_info=True)
			self._running = False
			self.stopped_event.set()

	def _run(self) -> None:
		"""
		PXEConfigWriter main method.

		This method creates a regular file and append the PXE boot configuration through
		to it. At the end the hooked callback is executed.
		"""

		logger.notice("Creating config %r and waiting for access", self.pxefiles)

		inotify = Inotify()

		for pxefile in self.pxefiles:
			if os.path.exists(pxefile):
				logger.debug("Removing old config file %r", pxefile)
				os.unlink(pxefile)

			logger.debug("Creating config file %r", pxefile)
			with open(pxefile, "w", encoding="utf-8") as file:
				file.write(self.content)
			shutil.chown(pxefile, -1, opsi_config.get("groups", "admingroup"))
			os.chmod(pxefile, 0o644)

			logger.debug("Watching config file %r for read with inotify", pxefile)

			inotify.add_watch(pxefile)

		file_accessed = None
		while not self._should_stop and not file_accessed:
			for event in inotify.event_gen(yield_nones=False, timeout_s=3):
				logger.trace("Inotify event: %s", event)
				(_, type_names, path, _filename) = event
				if "IN_CLOSE_NOWRITE" in type_names:
					file_accessed = path
					break

		if file_accessed:
			logger.info("Config file %r was accessed", file_accessed)
			if self._callback:
				self._callback(self)

		for pxefile in self.pxefiles:
			if os.path.exists(pxefile):
				logger.notice("Deleting config file %r", pxefile)
				os.unlink(pxefile)
			else:
				logger.notice("Config file %r already deleted", pxefile)

	def stop(self) -> None:
		"""
		Stop PXEConfigWriter thread.

		This method requests a stop for the current PXEConfigWriter instance.
		"""
		self._should_stop = True
