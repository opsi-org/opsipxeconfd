# -*- coding: utf-8 -*-
"""
:copyright: uib GmbH <info@uib.de>
This file is part of opsi - https://www.opsi.org

:license: GNU Affero General Public License version 3
"""
import argparse
import os
import shutil
from pathlib import Path
from socket import getfqdn
from unittest import mock

from opsicommon.types import forceHostId

from opsipxeconfd.pxeconfigwriter import PXEConfigWriter  # type: ignore[import]
from opsipxeconfd.setup import patchMenuFile # type: ignore[import]
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


def test_pxe_config_writer() -> None:
	host_id = forceHostId(getfqdn())
	pxe_config_template = os.path.join(TEST_DATA, PXE_TEMPLATE_FILE)
	append = {
		"pckey": "123",
		"hn": host_id.split(".")[0],
		"dn": ".".join(host_id.split(".")[1:]),
		"product": None,
		"service": "https://server.uib.gmbh:4447/rpc",
		"pwh": "$6$salt$password"
	}
	pcw = PXEConfigWriter(pxe_config_template, host_id, None, append, {}, CONFFILE, True, True)  # type: ignore[arg-type]
	content = pcw._get_pxe_config_content(pxe_config_template)  # pylint: disable=protected-access
	# opsi-install-x64
	# label opsi-install-x64
	# kernel install-x64
	# append initrd=miniroot-x64.bz2 video=vesa:ywrap,mtrr vga=791 quiet splash --no-log console=tty1 console=ttyS0
	#   hn=test dn=uib.gmbh product service
	assert "install-x64" in content
	assert "hn=test" in content
	assert "dn=uib.gmbh" in content
	assert "product" in content
	assert "service=https://server.uib.gmbh:4447/rpc" in content
	assert "pwh=$6$salt$password" in content

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
		"pwh": "$6$salt$password"
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
	assert "install-x64" in content
	assert "hn=test" in content
	assert "dn=uib.gmbh" in content
	assert "product" in content
	assert "service=https://server.uib.gmbh:4447/rpc" in content
	assert "pwh=$6$salt$password" in content

def test_service_patch_menu_file(tmp_path: Path) -> None:
	shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
	config = {'pxeDir': str(tmp_path)}
	patchMenuFile(config)
	grub_cfg = tmp_path / 'grub.cfg'
	content = grub_cfg.read_text(encoding='utf-8')
	print(content)
	assert 'service' in content
	assert 'pwh' not in content

def test_pwh_patch_menu_file(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return 'https://service.uib.gmbh:4447/rpc', ['pwh=$6$salt$123456']
	with mock.patch('opsipxeconfd.setup.getConfigsFromService', mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {'pxeDir': str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / 'grub.cfg'
		content = grub_cfg.read_text(encoding='utf-8')
		print(content)
		assert 'pwh=$6$salt$123456' in content
		assert 'https://service.uib.gmbh:4447/rpc' in content

def test_pwh_patch_menu_removal(tmp_path: Path) -> None:
	def mockGetConfigFromService() -> tuple[str, list[str]]:
		return 'https://service.uib.gmbh:4447/rpc', ['pwh=$6$salt$123456']
	with mock.patch('opsipxeconfd.setup.getConfigsFromService', mockGetConfigFromService):
		shutil.copytree(TEST_DATA, str(tmp_path), dirs_exist_ok=True)
		config = {'pxeDir': str(tmp_path)}
		patchMenuFile(config)
		grub_cfg = tmp_path / 'grub.cfg'
		content = grub_cfg.read_text(encoding='utf-8')
		print(content)
		assert 'pwh=$6$salt$123456' in content
		assert 'https://service.uib.gmbh:4447/rpc' in content
		def mockRemovePwhFromGrubCfg() -> tuple[str, list[str]]:
			return 'https://service.uib.gmbh:4447/rpc', []
		with mock.patch('opsipxeconfd.setup.getConfigsFromService', mockRemovePwhFromGrubCfg):
			patchMenuFile(config)
			content = grub_cfg.read_text(encoding='utf-8')
			print(content)
			assert 'pwh=$6$salt$123456' not in content
			assert 'https://service.uib.gmbh:4447/rpc' in content

def test_pid_file() -> None:
	if os.path.exists(PID_FILE):
		os.remove(PID_FILE)
	with pid_file(PID_FILE):
		with open(PID_FILE, "r", encoding="utf-8") as filehandle:
			pid = filehandle.readline().strip()
		assert not pid == ""
	assert not os.path.exists(PID_FILE)
