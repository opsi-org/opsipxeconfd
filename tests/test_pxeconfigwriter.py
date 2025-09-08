# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only


import os
import re
import shutil
import time
from pathlib import Path
from typing import Any
from unittest import mock

from opsicommon.objects import Host, NetbootProduct, OpsiClient, Product, ProductOnClient, ProductOnDepot
from opsicommon.types import forceHostId

from opsipxeconfd.opsipxeconfd import Opsipxeconfd
from opsipxeconfd.pxeconfigwriter import PXEConfigWriter
from opsipxeconfd.setup import password_hash

TEST_DATA = "tests/test_data/"
PXE_TEMPLATE_FILE = "install-x64"


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
	content = pcw._get_pxe_config_content()

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
	pcw = PXEConfigWriter(pxe_config_template, host_id, None, append, {}, "opsipxeconfd_data/opsipxeconfd.conf", True, True)  # type: ignore[arg-type]
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
		updated_host: Host | None = None

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
		assert isinstance(mock_service_client.updated_host, OpsiClient)

		data = (tmp_path / system_uuid).read_text(encoding="utf-8")
		print(data)
		match = re.search("^append.* otp=([a-z0-9]+)", data, re.MULTILINE)
		assert match
		otp = match.group(1)
		assert otp == mock_service_client.updated_host.oneTimePassword
