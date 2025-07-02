# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

"""
:copyright: uib GmbH <info@uib.de>
This file is part of opsi - https://www.opsi.org

:license: GNU Affero General Public License version 3
"""

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from unittest import mock

from opsicommon.objects import Host, NetbootProduct, OpsiClient, Product, ProductOnClient, ProductOnDepot
from opsicommon.types import forceHostId

from opsipxeconfd.opsipxeconfd import Opsipxeconfd  # type: ignore[import]
from opsipxeconfd.opsipxeconfdinit import OpsipxeconfdInit  # type: ignore[import]
from opsipxeconfd.pxeconfigwriter import PXEConfigWriter  # type: ignore[import]
from opsipxeconfd.setup import password_hash  # type: ignore[import]
from opsipxeconfd.setup import patchMenuFile
from opsipxeconfd.util import pid_file  # type: ignore[import]

default_opts = argparse.Namespace(
	help=False,
	version=False,
	nofork=False,
	conffile=None,
	setup=False,
	command="start",
	logLevel=7,
	logFile="/var/log/opsi/opsipxeconfd/opsipxeconfd.log",
	maxLogSize=5.0,
	keepRotatedLogs=1,
	logLevelFile=4,
	logLevelStderr=7,
	logFilter=None,
)

TEST_DATA = "tests/test_data/"
PXE_TEMPLATE_FILE = "install-x64"
CONFFILE = "/etc/opsi/opsipxeconfd.conf"
PID_FILE = "tests/test_data/pidfile.pid"


def test_process_config(tmp_path: Path) -> None:
	conf_file = tmp_path / "opsipxeconfd.conf"
	conf_file.write_text("pxe config template = /path\nmax control connections = 50\nuse mac address = false\n")
	with mock.patch.object(sys, "argv", ["opsipxeconfd", "-c", str(conf_file), "setup"]):
		init = OpsipxeconfdInit()
		init.process_config()
		assert init.config["pxeConfTemplate"] == "/path"
		assert init.config["maxConnections"] == 50
		assert init.config["useMacAddress"] is False


def test_pxe_config_writer(tmp_path: Path) -> None:
	host_id = forceHostId("client1.opsi.test")
	hostname, domain = host_id.split(".", 1)
	pxe_config_template = os.path.join(TEST_DATA, PXE_TEMPLATE_FILE)
	pxefiles = [tmp_path / "01-00-11-22-33-44-55", tmp_path / "11112222-3333-4444-5555-666677778888"]
	append = {
		"pckey": "123",
		"hn": host_id.split(".")[0],
		"dn": ".".join(host_id.split(".")[1:]),
		"product": None,
		"service": "https://server.uib.gmbh:4447/rpc",
		"pwh": "$6$salt$password",
		"acpi": None,
		"nomodeset": None,
		"nomsi": None,
		"lang": "de",
	}

	callback_pcw: PXEConfigWriter | None = None

	def callback(cpcw: PXEConfigWriter) -> None:
		nonlocal callback_pcw
		callback_pcw = cpcw
		time.sleep(2)

	pcw = PXEConfigWriter(
		template_file=pxe_config_template,
		host_id=host_id,
		product_on_client=None,  # type: ignore[arg-type]
		append=append,
		product_property_states={},
		pxefiles=[str(f) for f in pxefiles],
		secure_boot_module=True,
		uefi_module=True,
		callback=callback,
	)
	pcw.start()
	time.sleep(3)
	content = pcw._get_pxe_config_content()  # pylint: disable=protected-access
	# opsi-install-x64
	# label opsi-install-x64
	# kernel install-x64
	# append initrd=miniroot-x64.bz2 video=vesa:ywrap,mtrr vga=791 quiet splash --no-log console=tty1 console=ttyS0
	#   hn=test dn=uib.gmbh product service
	for pxefile in pxefiles:
		content = pxefile.read_text(encoding="utf-8")
		assert "install-x64" in content
		assert f"hn={hostname}" in content
		assert f"dn={domain}" in content
		assert "product" in content
		assert "service=https://server.uib.gmbh:4447/rpc" in content
		assert r"pwh=\$6\$salt\$password" in content
		assert "acpi" in content
		assert "nomodeset" in content
		assert "nomsi" in content
		assert "lang=de" in content
		assert "lang=en" not in content
		assert "test_hostname=client1" in content
		assert "test_domain=opsi.test" in content
		assert "test_fqdn=client1.opsi.test" in content
	time.sleep(2)  # wait for callback to finish
	assert callback_pcw is pcw
	pcw.stop()
	pcw.join(5)
	for pxefile in pxefiles:
		assert not pxefile.exists()


GRUB_PXE_TEMPLATE_FILE = "install-grub-x64"


def test_grub_pxe_config_writer() -> None:
	host_id = forceHostId("client1.opsi.test")
	pxe_config_template = os.path.join(TEST_DATA, GRUB_PXE_TEMPLATE_FILE)
	append = {
		"pckey": "123",
		"hn": host_id.split(".")[0],
		"dn": ".".join(host_id.split(".")[1:]),
		"product": None,
		"service": "https://server.uib.gmbh:4447/rpc",
		"pwh": r"$6$salt$password",
		"lang": "de",
	}
	pcw = PXEConfigWriter(pxe_config_template, host_id, None, append, {}, CONFFILE, True, True)  # type: ignore[arg-type]
	content = pcw._get_pxe_config_content()  # pylint: disable=protected-access
	# set timeout=0
	# menuentry 'Start netboot installation' {
	# set gfxpayload=keep
	# linux (pxe)/linux/install-x64 initrd=miniroot-x64 video=vesa:ywrap,mtrr vga=791 quiet splash --no-log console=tty1 console=ttyS0
	#   hn=test dn=uib.gmbh product service pwh=$6$salt$password
	# initrd (pxe)/linux/miniroot-x64
	# }
	assert "install-x64" in content
	assert "hn=client1" in content
	assert "dn=opsi.test" in content
	assert "product" in content
	assert "service=https://server.uib.gmbh:4447/rpc" in content
	assert r"pwh=\$6\$salt\$password" in content
	assert "lang=de" in content
	assert "lang=en" not in content
	assert "test_hostname=client1" in content
	assert "test_domain=opsi.test" in content
	assert "test_fqdn=client1.opsi.test" in content


def test_pxe_config_oneTimePassword(tmp_path: Path) -> None:
	shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
	client_id = "client1.opsi.test"
	system_uuid = "11112222-3333-4444-5555-666677778888"
	depot_id = "depot1.opsi.test"

	class MockServiceClient:
		updated_host: OpsiClient | None = None

		def host_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[Host]:
			if filter.get("id") == client_id:
				return [
					OpsiClient(
						id=client_id,
						systemUUID=system_uuid,
					)
				]

			return []

		def host_updateObjects(self, objects: list[Host]) -> None:
			self.updated_host = objects[0]

		def productOnClient_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[ProductOnClient]:
			return [
				ProductOnClient(
					productId="hwinvent",
					productType="NetbootProduct",
					clientId=client_id,
					actionRequest="setup",
				)
			]

		def productOnClient_updateObjects(self, objects: list[ProductOnClient]) -> None:
			pass

		def productOnDepot_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[ProductOnDepot]:
			return [
				ProductOnDepot(
					productId="hwinvent",
					productType="NetbootProduct",
					productVersion="4.3.0",
					packageVersion="1",
					depotId=depot_id,
				)
			]

		def product_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[Product]:
			return [
				NetbootProduct(
					id="hwinvent",
					productVersion="4.3.0",
					packageVersion="1",
				)
			]

		def productPropertyState_getValues(
			self,
			product_ids: list[str] | str | None = None,
			property_ids: list[str] | str | None = None,
			object_ids: list[str] | str | None = None,
			with_defaults: bool = True,
		) -> dict[str, dict[str, dict[str, list[Any]]]]:
			return {client_id: {}}

		def configState_getValues(
			self,
			config_ids: list[str] | str | None = None,
			object_ids: list[str] | str | None = None,
			with_defaults: bool = True,
		) -> dict[str, dict[str, list[Any]]]:
			return {
				client_id: {
					"clientconfig.configserver.url": ["https://service.uib.gmbh:4447/rpc"],
					"clientconfig.oneTimePassword": [password_hash("123456")],
				}
			}

	mock_service_client = MockServiceClient()

	pxe_config_template = os.path.join(tmp_path, PXE_TEMPLATE_FILE)
	with mock.patch("opsipxeconfd.opsipxeconfd.get_service_connection", return_value=mock_service_client):
		Opsipxeconfd(
			{
				"useOneTimePassword": True,
				"pxeDir": str(tmp_path),
				"pxeConfTemplate": pxe_config_template,
				"depotId": depot_id,
				"useMacAddress": False,
			}
		).update_boot_configuration(client_id)
		time.sleep(2)
		assert mock_service_client.updated_host

		data = (tmp_path / system_uuid).read_text(encoding="utf-8")
		print(data)
		match = re.search("^append.* otp=([a-z0-9]+)", data, re.MULTILINE)
		assert match
		otp = match.group(1)
		assert otp == mock_service_client.updated_host.oneTimePassword


########### GRUB CFG ################


def test_service_patch_menu_file(tmp_path: Path) -> None:
	shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
	config = {"pxeDir": str(tmp_path)}

	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", []

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub.cfg"
		with open(grub_cfg, "r", encoding="utf-8") as content:
			for line in content:
				if line.strip().startswith("linux"):
					assert "service=" in line
					assert "pwh=" not in line
					assert "lang=" not in line


def test_pwh_patch_menu_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		with mock.patch("opsipxeconfd.setup.grubSettings", return_value=False):
			shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
			config = {"pxeDir": str(tmp_path)}
			patchMenuFile(config)
			grub_cfg = tmp_path / "grub.cfg"
			with open(grub_cfg, "r", encoding="utf-8") as content:
				for line in content:
					if line.strip().startswith("linux"):
						assert r"pwh=\$6\$salt\$123456" in line
						assert "https://service.uib.gmbh:4447/rpc" in line
						assert "lang=de" not in line


def test_lang_patch_menu_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["lang=de"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		with mock.patch("opsipxeconfd.setup.grubSettings", return_value=False):
			shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
			config = {"pxeDir": str(tmp_path)}
			patchMenuFile(config)
			grub_cfg = tmp_path / "grub.cfg"
			with open(grub_cfg, "r", encoding="utf-8") as content:
				for line in content:
					if line.strip().startswith("linux"):
						assert "lang=de" in line
						assert "https://service.uib.gmbh:4447/rpc" in line
						assert "pwh=" not in line


def test_pwh_patch_menu_removal(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		with mock.patch("opsipxeconfd.setup.grubSettings", return_value=False):
			shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
			config = {"pxeDir": str(tmp_path)}
			patchMenuFile(config)
			grub_cfg = tmp_path / "grub.cfg"
			with open(grub_cfg, "r", encoding="utf-8") as content:
				for line in content:
					if line.strip().startswith("linux"):
						assert r"pwh=\$6\$salt\$123456" in line
						assert "https://service.uib.gmbh:4447/rpc" in line
						assert "lang=us" in line

			def mockRemovePwhFromGrubCfg() -> tuple[str, list[str]]:
				return "https://service.uib.gmbh:4447/rpc", [""]

			with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockRemovePwhFromGrubCfg):
				patchMenuFile(config)
				with open(grub_cfg, "r", encoding="utf-8") as content:
					for line in content:
						if line.strip().startswith("linux"):
							assert r"pwh=\$6\$salt\$123456" not in line
							assert "https://service.uib.gmbh:4447/rpc" in line
							assert "lang=us" not in line


def test_service_and_pwh_change(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		with mock.patch("opsipxeconfd.setup.grubSettings", return_value=False):
			shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
			config = {"pxeDir": str(tmp_path)}
			patchMenuFile(config)
			grub_cfg = tmp_path / "grub.cfg"
			with open(grub_cfg, "r", encoding="utf-8") as content:
				for line in content:
					if line.strip().startswith("linux"):
						assert r"pwh=\$6\$salt\$123456" in line
						assert "https://service.uib.gmbh:4447/rpc" in line
						assert "lang=us" in line

			def mockGetConfigFromService2() -> tuple[str, list[str]]:
				return "https://opsiserver.uib.gmbh:4447/rpc", ["pwh=$6$tlas$654321", "lang=de"]

			with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService2):
				patchMenuFile(config)
				with open(grub_cfg, "r", encoding="utf-8") as content:
					for line in content:
						if line.strip().startswith("linux"):
							assert "pwh=$6$salt$123456" not in line
							assert r"pwh=\$6\$tlas\$654321" in line
							assert "https://service.uib.gmbh:4447/rpc" not in line
							assert "https://opsiserver.uib.gmbh:4447/rpc" in line
							assert "lang=us" not in line
							assert "lang=de" in line


def test_service_patch_new_grub_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", []

	with (
		mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService),
		mock.patch("opsipxeconfd.setup.grubSettings", return_value=False),
	):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub.cfg"
		with open(grub_cfg, "r", encoding="utf-8") as content:
			for line in content:
				if line.strip().startswith("linux"):
					assert "service" in line
					assert "pwh=" not in line
					assert "lang=" not in line


def test_pwh_patch_new_grub_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		with mock.patch("opsipxeconfd.setup.grubSettings", return_value=False):
			shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
			config = {"pxeDir": str(tmp_path)}
			patchMenuFile(config)
			grub_cfg = tmp_path / "grub.cfg"
			with open(grub_cfg, "r", encoding="utf-8") as content:
				for line in content:
					if line.strip().startswith("linux"):
						assert r"pwh=\$6\$salt\$123456" in line
						assert "https://service.uib.gmbh:4447/rpc" in line
						assert "lang=de" not in line


def test_lang_patch_new_grub_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["lang=de"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		with mock.patch("opsipxeconfd.setup.grubSettings", return_value=False):
			shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
			config = {"pxeDir": str(tmp_path)}
			patchMenuFile(config)
			grub_cfg = tmp_path / "grub.cfg"
			with open(grub_cfg, "r", encoding="utf-8") as content:
				for line in content:
					if line.strip().startswith("linux"):
						assert "lang=de" in line
						assert "https://service.uib.gmbh:4447/rpc" in line
						assert "pwh=" not in line


def test_pwh_patch_new_grub_removal_in_grub_cfg(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		with mock.patch("opsipxeconfd.setup.grubSettings", return_value=False):
			shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
			config = {"pxeDir": str(tmp_path)}
			patchMenuFile(config)
			grub_cfg = tmp_path / "grub.cfg"
			with open(grub_cfg, "r", encoding="utf-8") as content:
				for line in content:
					if line.strip().startswith("linux"):
						assert r"pwh=\$6\$salt\$123456" in line
						assert "https://service.uib.gmbh:4447/rpc" in line
						assert "lang=us" in line

			def mockRemovePwhFromGrubCfg() -> tuple[str, list[str]]:
				return "https://service.uib.gmbh:4447/rpc", [""]

			with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockRemovePwhFromGrubCfg):
				patchMenuFile(config)
				with open(grub_cfg, "r", encoding="utf-8") as content:
					for line in content:
						if line.strip().startswith("linux"):
							assert r"pwh=\$6\$salt\$123456" not in line
							assert "https://service.uib.gmbh:4447/rpc" in line
							assert "lang=us" not in line


def test_service_and_pwh_change_in_grub_cfg(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		with mock.patch("opsipxeconfd.setup.grubSettings", return_value=False):
			shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
			config = {"pxeDir": str(tmp_path)}
			patchMenuFile(config)
			grub_cfg = tmp_path / "grub.cfg"
			with open(grub_cfg, "r", encoding="utf-8") as content:
				for line in content:
					if line.strip().startswith("linux"):
						assert r"pwh=\$6\$salt\$123456" in line
						assert "https://service.uib.gmbh:4447/rpc" in line
						assert "lang=us" in line

			def mockGetConfigFromService2() -> tuple[str, list[str]]:
				return "https://opsiserver.uib.gmbh:4447/rpc", ["pwh=$6$tlas$654321", "lang=de"]

			with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService2):
				patchMenuFile(config)
				with open(grub_cfg, "r", encoding="utf-8") as content:
					for line in content:
						if line.strip().startswith("linux"):
							assert "pwh=$6$salt$123456" not in line
							assert r"pwh=\$6\$tlas\$654321" in line
							assert "https://service.uib.gmbh:4447/rpc" not in line
							assert "https://opsiserver.uib.gmbh:4447/rpc" in line
							assert "lang=us" not in line
							assert "lang=de" in line


########### GRUB MENU ################


def test_service_patch_new_grub_menu_file(tmp_path: Path) -> None:
	shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
	config = {"pxeDir": str(tmp_path)}

	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", []

	with (
		mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService),
		mock.patch("opsipxeconfd.setup.grubSettings", return_value=False),
	):
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub-menu.cfg"
		with open(grub_cfg, "r", encoding="utf-8") as content:
			for line in content:
				if line.strip().startswith("linux"):
					assert "service=" in line
					assert "pwh=" not in line
					assert "lang=" not in line
					assert "${pwh}" not in line
					assert "${lang}" not in line


def test_pwh_patch_new_grub_menu_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		with mock.patch("opsipxeconfd.setup.grubSettings", return_value=False):
			shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
			config = {"pxeDir": str(tmp_path)}
			patchMenuFile(config)
			grub_cfg = tmp_path / "grub-menu.cfg"
			with open(grub_cfg, "r", encoding="utf-8") as content:
				for line in content:
					if line.strip().startswith("linux"):
						assert r"pwh=\$6\$salt\$123456" in line
						assert "https://service.uib.gmbh:4447/rpc" in line
						assert "lang=de" not in line
						assert "${pwh}" not in line
						assert "${lang}" not in line


def test_lang_patch_new_grub_menu_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["lang=de"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		with mock.patch("opsipxeconfd.setup.grubSettings", return_value=False):
			shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
			config = {"pxeDir": str(tmp_path)}
			patchMenuFile(config)
			grub_cfg = tmp_path / "grub-menu.cfg"
			with open(grub_cfg, "r", encoding="utf-8") as content:
				for line in content:
					if line.strip().startswith("linux"):
						assert "lang=de" in line
						assert "https://service.uib.gmbh:4447/rpc" in line
						assert "pwh=" not in line
						assert "${pwh}" not in line
						assert "${lang}" not in line


def test_pwh_patch_new_grub_removal_in_grub_menu(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		with mock.patch("opsipxeconfd.setup.grubSettings", return_value=False):
			shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
			config = {"pxeDir": str(tmp_path)}
			patchMenuFile(config)
			grub_cfg = tmp_path / "grub-menu.cfg"
			with open(grub_cfg, "r", encoding="utf-8") as content:
				for line in content:
					if line.strip().startswith("linux"):
						assert r"pwh=\$6\$salt\$123456" in line
						assert "https://service.uib.gmbh:4447/rpc" in line
						assert "lang=us" in line
						assert "${pwh}" not in line
						assert "${lang}" not in line

			def mockRemovePwhFromGrubCfg() -> tuple[str, list[str]]:
				return "https://service.uib.gmbh:4447/rpc", [""]

			with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockRemovePwhFromGrubCfg):
				patchMenuFile(config)
				with open(grub_cfg, "r", encoding="utf-8") as content:
					for line in content:
						if line.strip().startswith("linux"):
							assert r"pwh=\$6\$salt\$123456" not in line
							assert "https://service.uib.gmbh:4447/rpc" in line
							assert "lang=us" not in line
							assert "${pwh}" not in line
							assert "${lang}" not in line


def test_service_and_pwh_change_in_grub_menu(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		with mock.patch("opsipxeconfd.setup.grubSettings", return_value=False):
			shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
			config = {"pxeDir": str(tmp_path)}
			patchMenuFile(config)
			grub_cfg = tmp_path / "grub-menu.cfg"
			with open(grub_cfg, "r", encoding="utf-8") as content:
				for line in content:
					if line.strip().startswith("linux"):
						assert r"pwh=\$6\$salt\$123456" in line
						assert "https://service.uib.gmbh:4447/rpc" in line
						assert "lang=us" in line
						assert "${pwh}" not in line
						assert "${lang}" not in line

			def mockGetConfigFromService2() -> tuple[str, list[str]]:
				return "https://opsiserver.uib.gmbh:4447/rpc", ["pwh=$6$tlas$654321", "lang=de"]

			with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService2):
				patchMenuFile(config)
				with open(grub_cfg, "r", encoding="utf-8") as content:
					for line in content:
						if line.strip().startswith("linux"):
							assert "pwh=$6$salt$123456" not in line
							assert r"pwh=\$6\$tlas\$654321" in line
							assert "https://service.uib.gmbh:4447/rpc" not in line
							assert "https://opsiserver.uib.gmbh:4447/rpc" in line
							assert "lang=us" not in line
							assert "lang=de" in line
							assert "${pwh}" not in line
							assert "${lang}" not in line


########### GRUB SETTINGS ################


def test_read_grub_settings_file(tmp_path: Path) -> None:
	shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
	config = {"pxeDir": str(tmp_path)}

	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", []

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		patchMenuFile(config)

	grub_cfg = tmp_path / "grub-settings.cfg"
	content = grub_cfg.read_text(encoding="utf-8")
	assert "set timeout=5" in content
	assert 'set graphicsmode="true"' in content
	assert 'set passwordhash=""' in content
	assert 'set language=""' in content


def test_write_hash_and_lang_in_grub_settings_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub-settings.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		assert "timeout" in content
		assert "graphics" in content
		assert r'set passwordhash="\$6\$salt\$123456"' in content
		assert 'set language="us"' in content

		grub_menu = tmp_path / "grub-menu.cfg"
		with open(grub_menu, "r", encoding="utf-8") as content_menu:
			for line in content_menu:
				if line.strip().startswith("linux"):
					assert r"pwh=\$6\$salt\$123456" not in line
					assert "https://service.uib.gmbh:4447/rpc" in line
					assert "lang=us" not in line


def test_change_hash_and_lang_in_grub_settings_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub-settings.cfg"
		grub_menu = tmp_path / "grub-menu.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		assert "timeout" in content
		assert "graphics" in content
		assert r'set passwordhash="\$6\$salt\$123456"' in content
		assert 'set language="us"' in content
		with open(grub_menu, "r", encoding="utf-8") as content_menu:
			for line in content_menu:
				if line.strip().startswith("linux"):
					assert r"pwh=\$6\$salt\$123456" not in line
					assert "https://service.uib.gmbh:4447/rpc" in line
					assert "lang=us" not in line
					assert "${pwh}" in line
					assert "${lang}" in line

		def mockGetConfigFromService2() -> tuple[str, list[str]]:
			return "https://opsiserver.uib.gmbh:4447/rpc", ["pwh=$6$tlas$654321", "lang=de"]

		with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService2):
			patchMenuFile(config)
			content = grub_cfg.read_text(encoding="utf-8")
			assert r'set passwordhash="\$6\$salt\$123456"' not in content
			assert r'set passwordhash="\$6\$tlas\$654321"' in content
			assert 'set language="us"' not in content
			assert 'set language="de"' in content
			with open(grub_menu, "r", encoding="utf-8") as content_menu:
				for line in content_menu:
					if line.strip().startswith("linux"):
						assert r"pwh=\$6\$salt\$123456" not in line
						assert r"pwh=\$6\$tlas\$654321" not in line
						assert "https://service.uib.gmbh:4447/rpc" not in line
						assert "https://opsiserver.uib.gmbh:4447/rpc" in line
						assert "lang=us" not in line
						assert "lang=de" not in line
						assert "${pwh}" in line
						assert "${lang}" in line


def test_remove_hash_and_lang_in_grub_settings_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub-settings.cfg"
		grub_menu = tmp_path / "grub-menu.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		assert "timeout" in content
		assert "graphics" in content
		assert r'set passwordhash="\$6\$salt\$123456"' in content
		assert 'set language="us"' in content

		with open(grub_menu, "r", encoding="utf-8") as content_menu:
			for line in content_menu:
				if line.strip().startswith("linux"):
					assert r"pwh=\$6\$salt\$123456" not in line
					assert "https://service.uib.gmbh:4447/rpc" in line
					assert "lang=us" not in line
					assert "${pwh}" in line
					assert "${lang}" in line

		def mockRemovePwhFromGrubCfg() -> tuple[str, list[str]]:
			return "https://service.uib.gmbh:4447/rpc", [""]

		with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockRemovePwhFromGrubCfg):
			patchMenuFile(config)
			content = grub_cfg.read_text(encoding="utf-8")
			assert r'set passwordhash="\$6\$salt\$123456"' not in content
			assert 'set passwordhash=""' in content
			assert 'set language="us"' not in content
			assert 'set language="en"' not in content
			assert 'set language=""' in content

			with open(grub_menu, "r", encoding="utf-8") as content_menu:
				for line in content_menu:
					if line.strip().startswith("linux"):
						assert r"pwh=\$6\$salt\$123456" not in line
						assert "https://service.uib.gmbh:4447/rpc" in line
						assert "lang=" not in line
						assert "${pwh}" in line
						assert "${lang}" in line


########### OTHER ################


def test_pid_file() -> None:
	if os.path.exists(PID_FILE):
		os.remove(PID_FILE)
	with pid_file(PID_FILE):
		with open(PID_FILE, "r", encoding="utf-8") as filehandle:
			pid = filehandle.readline().strip()
		assert not pid == ""
	assert not os.path.exists(PID_FILE)


def test_password_hash() -> None:
	with mock.patch("purecrypt.Crypt.generate_salt", lambda _hash_type: "$6$0123456789abcdef"):
		pw_hash = password_hash("password1234")
	# mkpasswd -m sha-512 -S 0123456789abcdef -R 5000 password1234
	assert pw_hash == "$6$0123456789abcdef$EfziIn9cELczcFpjUwHWzRm8Cb03CHBpyUyE4asFools/Zzi3Z7f1wvR6OtOix0zzr81ROdRdJowCWdk37Wo00"

	for password in ("password1234", "üw9Ä%$3kföd&3ä3k!"):
		pw_hash2 = password_hash(password)
		assert "." not in pw_hash2
		assert pw_hash != pw_hash2
		parts = pw_hash.split("$")
		assert len(parts) == 4
		assert parts[0] == ""
		assert parts[1] == "6"  # $6$ is SHA-512
		assert len(parts[2]) == 16  # salt len 16
		
