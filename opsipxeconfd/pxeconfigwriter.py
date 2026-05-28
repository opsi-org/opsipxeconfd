# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

from __future__ import annotations

import shutil
import time
from pathlib import Path
from threading import Event, Thread
from typing import Callable

from inotify.adapters import Inotify
from opsi.logging import get_logger, log_context
from opsi.opsi.service.server import OpsiConfig

from opsipxeconfd.template import TemplateContext, render_grub_cfg

logger = get_logger()
opsi_config = OpsiConfig()


class PXEConfigWriter(Thread):
	"""
	class PXEConfigWriter

	This class handles the sending of PXE boot information to clients.
	"""

	def __init__(
		self,
		context: TemplateContext,
		pxefiles: list[Path],
		callback: Callable | None = None,
	) -> None:
		Thread.__init__(self)
		self.daemon = True
		self.context = context
		self.pxefiles = pxefiles
		self._callback = callback
		self._should_stop = False
		self.error: Exception | None = None
		self.start_time = time.time()
		self.ready_event = Event()
		self.stopped_event = Event()

		logger.debug("PXEConfigWriter initializing: host_id %r, pxefiles %r", self.host_id, ", ".join(str(f) for f in self.pxefiles))

		if not self.context.product:
			raise ValueError("PXEConfigWriter needs a product in context")

	@property
	def host_id(self) -> str:
		return self.context.host.id

	@property
	def product_id(self) -> str:
		assert self.context.product
		return self.context.product.product.id

	def run(self) -> None:
		with log_context({"instance": "PXEConfigWriter"}):
			try:
				self._run()
			except Exception as err:
				logger.error(err, exc_info=True)
				self.error = err
			self.ready_event.set()
			self.stopped_event.set()

	def _run(self) -> None:
		"""
		PXEConfigWriter main method.

		This method creates a regular file and append the PXE boot configuration through
		to it. At the end the hooked callback is executed.
		"""
		logger.info("Creating config(s) %r and waiting for access", ", ".join(str(f) for f in self.pxefiles))

		inotify = Inotify()

		grub_cfg = render_grub_cfg(self.context)

		for pxefile in self.pxefiles:
			if pxefile.exists():
				logger.debug("Removing old config file '%s'", pxefile)
				pxefile.unlink()

			logger.debug("Creating config file '%s'", pxefile)
			logger.trace(grub_cfg)
			pxefile.write_text(grub_cfg, encoding="utf-8")
			try:
				shutil.chown(pxefile, -1, opsi_config.get("groups", "admingroup"))
				pxefile.chmod(0o644)
			except Exception as err:
				logger.error("Failed to set permissions on '%s': %s", pxefile, err)

			logger.debug("Watching config file '%s' for read with inotify", pxefile)

			inotify.add_watch(str(pxefile))

		self.ready_event.set()

		file_accessed = None
		while not self._should_stop and not file_accessed:
			for event in inotify.event_gen(yield_nones=False, timeout_s=3):
				logger.trace("Inotify event: %s", event)
				(_, type_names, path, _filename) = event
				if "IN_CLOSE_NOWRITE" in type_names:
					file_accessed = path
					break

		for pxefile in self.pxefiles:
			try:
				inotify.remove_watch(str(pxefile))
			except Exception as err:
				logger.error("Failed to remove inotify watch for '%s': %s", pxefile, err)

		if file_accessed:
			logger.notice("Config file '%s' was accessed", file_accessed)
			if self._callback:
				self._callback(self)

		for pxefile in self.pxefiles:
			if pxefile.exists():
				logger.info("Deleting config file '%s'", pxefile)
				try:
					pxefile.unlink()
				except Exception as err:
					logger.error("Failed to delete config file '%s': %s", pxefile, err)
			else:
				logger.info("Config file '%s' already deleted", pxefile)

	def stop(self) -> None:
		"""
		Stop PXEConfigWriter thread.

		This method requests a stop for the current PXEConfigWriter instance.
		"""
		self._should_stop = True
