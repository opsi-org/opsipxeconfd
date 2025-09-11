# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

import shutil
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from opsicommon.client.opsiservice import ServiceClient
from opsicommon.objects import OpsiDepotserver

from opsipxeconfd.setup import setup_grub_cfg


def test_setup_grub_cfg(tmp_path: Path) -> None:
	grub_cfg_template = Path(tmp_path) / "template" / "grub.cfg"
	grub_cfg_template.parent.mkdir()
	default_product_grub_cfg = tmp_path / "opsi-linux-bootimage" / "grub.cfg"
	default_product_grub_cfg.parent.mkdir()
	default_product_grub_cfg.write_text(
		dedent("""
		menuentry 'Start netboot installation' {
			echo "Loading opsi-linux-bootimage - please wait..."
			linux (${bootsrc})/opsi/opsi-linux-bootimage/kernel.${arch} {{ linux.cmdline("netboot.linux-bootimage.cmdline") }}
			initrd (${bootsrc})/opsi/opsi-linux-bootimage/initramfs.${arch}
			echo "Starting opsi-linux-bootimage - please wait..."
		}
		"""),
		encoding="utf-8",
	)

	shutil.copy(Path("tests/data/grub.cfg"), grub_cfg_template)
	grub_cfg = Path(tmp_path) / "grub.cfg"

	depot_id = "depot1.opsi.test"
	config_state_values: dict[str, dict[str, list[str | bool]]] = {
		depot_id: {
			"clientconfig.configserver.url": ["http://opsi.test:4447/rpc"],
		}
	}

	def mock_get_service_connection() -> ServiceClient:
		client = ServiceClient()
		setattr(
			client,
			"host_getObjects",
			lambda **kwargs: [
				OpsiDepotserver(
					id=depot_id,
				)
			],
		)
		setattr(
			client,
			"configState_getValues",
			lambda **kwargs: config_state_values,
		)
		return client

	with (
		patch("opsipxeconfd.template.GRUB_CFG_TEMPLATE", str(grub_cfg_template)),
		patch("opsipxeconfd.template.DEFAULT_PRODUCT_GRUB_CFG", str(default_product_grub_cfg)),
		patch("opsipxeconfd.template.get_service_connection", mock_get_service_connection),
		patch("opsipxeconfd.setup.GRUB_CFG", str(grub_cfg)),
		patch("opsipxeconfd.setup.get_service_connection", mock_get_service_connection),
	):
		setup_grub_cfg()
		data = grub_cfg.read_text(encoding="utf-8")
		# print(data)
		assert 'echo "gfxmode"' not in data
		assert "set timeout=5" in data
		assert "menuentry 'Local Disk' {" in data

		config_state_values = {
			depot_id: {
				"clientconfig.configserver.url": ["http://opsi.test:4447/rpc"],
				"netboot.grub.timeout": ["10"],
				"netboot.grub.additional_menu_entries": ["menuentry 'Test' { echo 'Test'; }"],
				"netboot.grub.graphicsmode": [True],
				"netboot.grub.password": ["secret"],
				"netboot.linux-bootimage.cmdline.splash": [True],
			}
		}
		setup_grub_cfg()
		data = grub_cfg.read_text(encoding="utf-8")
		print(data)
		assert 'echo "gfxmode"' in data
		assert 'echo "password: $1$' in data
		assert "set timeout=10" in data
		assert (
			dedent("""
			menuentry 'Start netboot installation' {
				echo "Loading opsi-linux-bootimage - please wait..."
				linux (${bootsrc})/opsi/opsi-linux-bootimage/kernel.${arch} service=http://opsi.test:4447/rpc splash
				initrd (${bootsrc})/opsi/opsi-linux-bootimage/initramfs.${arch}
				echo "Starting opsi-linux-bootimage - please wait..."
			}
		""")
			in data
		)
		assert "menuentry 'Test' { echo 'Test'; }" in data
