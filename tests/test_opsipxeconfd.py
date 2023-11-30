# -*- coding: utf-8 -*-
"""
:copyright: uib GmbH <info@uib.de>
This file is part of opsi - https://www.opsi.org

:license: GNU Affero General Public License version 3
"""
import argparse
import os
import shutil
import time
from pathlib import Path
from socket import getfqdn
from unittest import mock

from opsicommon.types import forceHostId

from opsipxeconfd.pxeconfigwriter import PXEConfigWriter  # type: ignore[import]
from opsipxeconfd.setup import patchMenuFile  # type: ignore[import]
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


def test_pxe_config_writer(tmp_path: Path) -> None:
	host_id = forceHostId(getfqdn())
	hostname, domain = host_id.split(".", 1)
	pxe_config_template = os.path.join(TEST_DATA, PXE_TEMPLATE_FILE)
	pxefiles = [tmp_path / "01-00-11-22-33-44-55", tmp_path / "11112222-3333-4444-5555-666677778888"]
	append = {
		"pckey": "123",
		"hn": host_id.split(".")[0],
		"dn": ".".join(host_id.split(".")[1:]),
		"product": None,
		"service": "https://server.uib.gmbh:4447/rpc",
		"pwh": r"\$6\$salt\$password",
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
		product_on_client=None,
		append=append,
		product_property_states={},
		pxefiles=[str(f) for f in pxefiles],
		secure_boot_module=True,
		uefi_module=True,
		callback=callback,
	)
	pcw.start()
	time.sleep(3)
	content = pcw._get_pxe_config_content(pxe_config_template)  # pylint: disable=protected-access
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
	assert callback_pcw is pcw
	pcw.stop()
	pcw.join(5)
	for pxefile in pxefiles:
		assert not pxefile.exists()


GRUB_PXE_TEMPLATE_FILE = "install-grub-x64"


def test_grub_pxe_config_writer() -> None:
	host_id = forceHostId(getfqdn())
	pxe_config_template = os.path.join(TEST_DATA, GRUB_PXE_TEMPLATE_FILE)
	append = {
		"pckey": "123",
		"hn": host_id.split(".")[0],
		"dn": ".".join(host_id.split(".")[1:]),
		"product": None,
		"service": "https://server.uib.gmbh:4447/rpc",
		"pwh": r"\$6\$salt\$password",
		"lang": "de",
	}
	pcw = PXEConfigWriter(pxe_config_template, host_id, None, append, {}, CONFFILE, True, True)  # type: ignore[arg-type]
	content = pcw._get_pxe_config_content(pxe_config_template)  # pylint: disable=protected-access
	# set timeout=0
	# menuentry 'Start netboot installation' {
	# set gfxpayload=keep
	# linux (pxe)/linux/install-x64 initrd=miniroot-x64 video=vesa:ywrap,mtrr vga=791 quiet splash --no-log console=tty1 console=ttyS0
	#   hn=test dn=uib.gmbh product service pwh=$6$salt$password
	# initrd (pxe)/linux/miniroot-x64
	# }
	for line in content:
		if line.strip().startswith("linux"):
			assert "install-x64" in line
			assert "hn=test" in line
			assert "dn=uib.gmbh" in line
			assert "product" in line
			assert "service=https://server.uib.gmbh:4447/rpc" in line
			assert r"pwh=\$6\$salt\$password" in line
			assert "lang=de" in line


########### OLD GRUB CFG ################


def test_service_patch_menu_file(tmp_path: Path) -> None:
	shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
	config = {"pxeDir": str(tmp_path)}
	patchMenuFile(config)
	grub_cfg = tmp_path / "grub.cfg"
	content = grub_cfg.read_text(encoding="utf-8")
	for line in content:
		if line.strip().startswith("linux"):
			assert "service" in line
			assert "pwh" not in line
			assert "lang" not in line


def test_pwh_patch_menu_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		for line in content:
			if line.strip().startswith("linux"):
				assert r"pwh=\$6\$salt\$123456" in line
				assert "https://service.uib.gmbh:4447/rpc" in line
				assert "lang=de" not in line


def test_lang_patch_menu_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["lang=de"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		for line in content:
			if line.strip().startswith("linux"):
				assert "lang=de" in line
				assert "https://service.uib.gmbh:4447/rpc" in line
				assert "pwh" not in line


def test_pwh_patch_menu_removal(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		for line in content:
			if line.strip().startswith("linux"):
				assert r"pwh=\$6\$salt\$123456" in line
				assert "https://service.uib.gmbh:4447/rpc" in line
				assert "lang=us" in line

		def mockRemovePwhFromGrubCfg() -> tuple[str, list[str]]:
			return "https://service.uib.gmbh:4447/rpc", [""]

		with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockRemovePwhFromGrubCfg):
			patchMenuFile(config)
			content = grub_cfg.read_text(encoding="utf-8")
			for line in content:
				if line.strip().startswith("linux"):
					assert r"pwh=\$6\$salt\$123456" not in line
					assert "https://service.uib.gmbh:4447/rpc" in line
					assert "lang=us" not in line


def test_service_and_pwh_change(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		for line in content:
			if line.strip().startswith("linux"):
				assert r"pwh=\$6\$salt\$123456" in line
				assert "https://service.uib.gmbh:4447/rpc" in line
				assert "lang=us" in line

		def mockGetConfigFromService2() -> tuple[str, list[str]]:
			return "https://opsiserver.uib.gmbh:4447/rpc", ["pwh=$6$tlas$654321", "lang=de"]

		with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService2):
			patchMenuFile(config)
			content = grub_cfg.read_text(encoding="utf-8")
			for line in content:
				if line.strip().startswith("linux"):
					assert "pwh=$6$salt$123456" not in line
					assert r"pwh=\$6\$tlas\$654321" in line
					assert "https://service.uib.gmbh:4447/rpc" not in line
					assert "https://opsiserver.uib.gmbh:4447/rpc" in line
					assert "lang=us" not in line
					assert "lang=de" in line


########### GRUB CFG ################


def test_service_patch_new_grub_file(tmp_path: Path) -> None:
	shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
	config = {"pxeDir": str(tmp_path)}
	patchMenuFile(config)
	grub_cfg = tmp_path / "grub.cfg"
	content = grub_cfg.read_text(encoding="utf-8")
	for line in content:
		if line.strip().startswith("linux"):
			assert "service" not in line
			assert "pwh" not in line
			assert "lang" not in line


def test_pwh_patch_new_grub_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		for line in content:
			if line.strip().startswith("linux"):
				assert r"pwh=\$6\$salt\$123456" not in line
				assert "https://service.uib.gmbh:4447/rpc" not in line
				assert "lang=de" not in line


def test_lang_patch_new_grub_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["lang=de"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		for line in content:
			if line.strip().startswith("linux"):
				assert "lang=de" not in line
				assert "https://service.uib.gmbh:4447/rpc" not in line
				assert "pwh" not in line


def test_pwh_patch_new_grub_removal_in_grub_cfg(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		for line in content:
			if line.strip().startswith("linux"):
				assert r"pwh=\$6\$salt\$123456" not in line
				assert "https://service.uib.gmbh:4447/rpc" not in line
				assert "lang=us" not in line

		def mockRemovePwhFromGrubCfg() -> tuple[str, list[str]]:
			return "https://service.uib.gmbh:4447/rpc", [""]

		with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockRemovePwhFromGrubCfg):
			patchMenuFile(config)
			content = grub_cfg.read_text(encoding="utf-8")
			for line in content:
				if line.strip().startswith("linux"):
					assert r"pwh=\$6\$salt\$123456" not in line
					assert "https://service.uib.gmbh:4447/rpc" not in line
					assert "lang=us" not in line


def test_service_and_pwh_change_in_grub_cfg(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		for line in content:
			if line.strip().startswith("linux"):
				assert r"pwh=\$6\$salt\$123456" not in line
				assert "https://service.uib.gmbh:4447/rpc" not in line
				assert "lang=us" not in line

		def mockGetConfigFromService2() -> tuple[str, list[str]]:
			return "https://opsiserver.uib.gmbh:4447/rpc", ["pwh=$6$tlas$654321", "lang=de"]

		with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService2):
			patchMenuFile(config)
			content = grub_cfg.read_text(encoding="utf-8")
			for line in content:
				if line.strip().startswith("linux"):
					assert "pwh=$6$salt$123456" not in line
					assert r"pwh=\$6\$tlas\$654321" not in line
					assert "https://service.uib.gmbh:4447/rpc" not in line
					assert "https://opsiserver.uib.gmbh:4447/rpc" not in line
					assert "lang=us" not in line
					assert "lang=de" not in line


########### GRUB MENU ################


def test_service_patch_new_grub_menu_file(tmp_path: Path) -> None:
	shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
	config = {"pxeDir": str(tmp_path)}
	patchMenuFile(config)
	grub_cfg = tmp_path / "grub-menu.cfg"
	content = grub_cfg.read_text(encoding="utf-8")
	for line in content:
		if line.strip().startswith("linux"):
			assert "service" not in line
			assert "pwh" not in line
			assert "lang" not in line


def test_pwh_patch_new_grub_menu_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub-menu.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		for line in content:
			if line.strip().startswith("linux"):
				assert r"pwh=\$6\$salt\$123456" in line
				assert "https://service.uib.gmbh:4447/rpc" in line
				assert "lang=de" not in line


def test_lang_patch_new_grub_menu_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["lang=de"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub-menu.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		for line in content:
			if line.strip().startswith("linux"):
				assert "lang=de" in line
				assert "https://service.uib.gmbh:4447/rpc" in line
				assert "pwh" not in line


def test_pwh_patch_new_grub_removal_in_grub_menu(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub-menu.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		for line in content:
			if line.strip().startswith("linux"):
				assert r"pwh=\$6\$salt\$123456" in line
				assert "https://service.uib.gmbh:4447/rpc" in line
				assert "lang=us" in line

		def mockRemovePwhFromGrubCfg() -> tuple[str, list[str]]:
			return "https://service.uib.gmbh:4447/rpc", [""]

		with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockRemovePwhFromGrubCfg):
			patchMenuFile(config)
			content = grub_cfg.read_text(encoding="utf-8")
			for line in content:
				if line.strip().startswith("linux"):
					assert r"pwh=\$6\$salt\$123456" not in line
					assert "https://service.uib.gmbh:4447/rpc" in line
					assert "lang=us" not in line


def test_service_and_pwh_change_in_grub_menu(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return "https://service.uib.gmbh:4447/rpc", ["pwh=$6$salt$123456", "lang=us"]

	with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {"pxeDir": str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / "grub-menu.cfg"
		content = grub_cfg.read_text(encoding="utf-8")
		for line in content:
			if line.strip().startswith("linux"):
				assert r"pwh=\$6\$salt\$123456" in line
				assert "https://service.uib.gmbh:4447/rpc" in line
				assert "lang=us" in line

		def mockGetConfigFromService2() -> tuple[str, list[str]]:
			return "https://opsiserver.uib.gmbh:4447/rpc", ["pwh=$6$tlas$654321", "lang=de"]

		with mock.patch("opsipxeconfd.setup.getConfigsFromService", mockGetConfigFromService2):
			patchMenuFile(config)
			content = grub_cfg.read_text(encoding="utf-8")
			for line in content:
				if line.strip().startswith("linux"):
					assert "pwh=$6$salt$123456" not in line
					assert r"pwh=\$6\$tlas\$654321" in line
					assert "https://service.uib.gmbh:4447/rpc" not in line
					assert "https://opsiserver.uib.gmbh:4447/rpc" in line
					assert "lang=us" not in line
					assert "lang=de" in line


def test_pid_file() -> None:
	if os.path.exists(PID_FILE):
		os.remove(PID_FILE)
	with pid_file(PID_FILE):
		with open(PID_FILE, "r", encoding="utf-8") as filehandle:
			pid = filehandle.readline().strip()
		assert not pid == ""
	assert not os.path.exists(PID_FILE)
