# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

import os

from opsi.opsi.service.server import OpsiConfig
from opsi.system.info import linux_distro_id_like

__version__ = "4.3.9.2"

LOG_FILE = "/var/log/opsi/opsipxeconfd/opsipxeconfd.log"
ERROR_MARKER = "(ERROR)"
CONFIG_FILE = "/etc/opsi/opsipxeconfd.conf"
PID_FILE = "/var/run/opsipxeconfd/opsipxeconfd.pid"
TFTP_DIR = "/tftpboot"
if linux_distro_id_like().intersection({"opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles"}) or (
	not os.path.exists(TFTP_DIR) and os.path.exists("/var/lib/tftpboot")
):
	TFTP_DIR = "/var/lib/tftpboot"
OPSI_PXE_DIR = f"{TFTP_DIR}/opsi"
PXE_CONFIG_DIR = f"{OPSI_PXE_DIR}/cfg"
LINUX_BOOTIMAGE_DIR = f"{OPSI_PXE_DIR}/opsi-linux-bootimage"
LEGACY_PXE_CONFIG_DIR = f"{LINUX_BOOTIMAGE_DIR}/cfg"
GRUB_CFG_TEMPLATE = "/usr/share/opsipxeconfd/grub.cfg"
GRUB_CFG = f"{PXE_CONFIG_DIR}/grub.cfg"
DEFAULT_PRODUCT_GRUB_CFG = f"{LINUX_BOOTIMAGE_DIR}/grub.cfg"
GRUB_CFG_MAX_UPDATE_INTERVAL = 10

opsi_config = OpsiConfig()


def get_depot_id() -> str:
	return opsi_config.get("host", "id")
