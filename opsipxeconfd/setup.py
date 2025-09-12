# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

from pathlib import Path
from threading import Lock

from opsicommon.logging import get_logger
from opsicommon.objects import OpsiDepotserver
from opsicommon.server.rights import set_rights
from opsicommon.server.setup import setup_users_and_groups as po_setup_users_and_groups

from opsipxeconfd import GRUB_CFG, LOG_FILE, PXE_CONFIG_DIR, get_depot_id
from opsipxeconfd.service import get_messagebus_listener, get_service_connection
from opsipxeconfd.template import get_template_context, render_grub_cfg

logger = get_logger()


def running_in_docker() -> bool:
	try:
		with open("/proc/2/stat", encoding="utf-8", errors="replace") as file:
			return "kthreadd" not in file.read()
	except FileNotFoundError:
		return True
	except Exception:
		pass
	return False


def setup_files() -> None:
	logger.info("Setup files and permissions")

	log_dir = Path(LOG_FILE).parent
	log_dir.mkdir(parents=True, exist_ok=True)
	set_rights(log_dir)

	pxe_config_dir = Path(PXE_CONFIG_DIR)
	pxe_config_dir.mkdir(parents=True, exist_ok=True)
	set_rights(pxe_config_dir)


def setup_limits() -> None:
	"""
	Setup for limits.

	This method sets up limits for the opsipxeconfd process.
	"""
	logger.notice("Setting up limits")
	if running_in_docker():
		logger.info("Running in docker, not setting limits")
		return

	min_value = 8192
	for limit in ("max_user_instances", "max_user_watches"):
		try:
			with open(f"/proc/sys/fs/inotify/{limit}", "r", encoding="ascii") as file:
				value = int(file.read().strip())
				if value < min_value:
					logger.info("Setting /proc/sys/fs/inotify/%s to %d", limit, min_value)
					with open(f"/proc/sys/fs/inotify/{limit}", "w", encoding="ascii") as file:
						file.write(str(min_value))
		except OSError as err:
			logger.warning("Failed to set %s: %s", limit, err)


setup_grub_cfg_lock = Lock()


def setup_grub_cfg() -> None:
	with setup_grub_cfg_lock:
		logger.notice("Setting up GRUB configuration")
		depot_id = get_depot_id()
		service = get_service_connection()
		try:
			depot: OpsiDepotserver = service.host_getObjects(id=depot_id)[0]  # type: ignore[attr-defined]
		except IndexError:
			raise RuntimeError(f"Depot {depot_id!r} not found") from None

		context = get_template_context(host=depot)
		data = render_grub_cfg(context)
		grub_cfg = Path(GRUB_CFG)
		grub_cfg.write_text(data, encoding="utf-8")
		set_rights(grub_cfg)


def setup() -> None:
	logger.notice("Running opsipxeconfd setup")
	setup_limits()
	po_setup_users_and_groups()
	setup_files()
	setup_grub_cfg()

	get_messagebus_listener().set_netboot_config_changed_callback(setup_grub_cfg)

	logger.notice("Setup finished")
