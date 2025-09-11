# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

import re
import shutil
from pathlib import Path
from threading import Event
from typing import Any
from unittest import mock

from opsicommon.objects import Host, NetbootProduct, OpsiClient, Product, ProductOnClient, ProductOnDepot

from opsipxeconfd.opsipxeconfd import Opsipxeconfd
from opsipxeconfd.pxeconfigwriter import PXEConfigWriter
from opsipxeconfd.template import TemplateContext


def test_pxe_config_writer(tmp_path: Path) -> None:
	host = OpsiClient(id="client1.opsi.test")
	product = NetbootProduct(
		id="product1", productVersion="1.0", packageVersion="1", pxeConfigTemplate="%host_id%\ngrub-cfg\n{{ host.id }}\n"
	)
	context = TemplateContext(
		host=host,
		product=product,
	)
	pxefiles = [tmp_path / "01-00-11-22-33-44-55", tmp_path / "11112222-3333-4444-5555-666677778888"]

	grub_cfg_template = Path(tmp_path) / "template" / "grub.cfg"
	grub_cfg_template.parent.mkdir(parents=True, exist_ok=True)
	shutil.copy(Path("tests/data/grub.cfg"), grub_cfg_template)

	callback_pcw: PXEConfigWriter | None = None

	callback_done = Event()

	def callback(cpcw: PXEConfigWriter) -> None:
		nonlocal callback_pcw
		callback_pcw = cpcw
		callback_done.set()

	with mock.patch("opsipxeconfd.template.GRUB_CFG_TEMPLATE", str(grub_cfg_template)):
		pcw = PXEConfigWriter(
			context=context,
			pxefiles=pxefiles,
			callback=callback,
		)
		pcw.start()

		pcw.ready_event.wait(5)
		assert pcw.error is None

	for pxefile in pxefiles:
		data = pxefile.read_text(encoding="utf-8")
		assert "grub_platform" in data
		assert f"{host.id}\ngrub-cfg\n{host.id}\n" in data

	# Wait for callback to finish
	callback_done.wait(5)

	assert callback_pcw is pcw
	pcw.stop()
	pcw.join(5)
	for pxefile in pxefiles:
		assert not pxefile.exists()


def test_pxe_config_oneTimePassword(tmp_path: Path) -> None:
	depot_id = "depot1.opsi.test"
	client_id = "client1.opsi.test"
	system_uuid = "11112222-3333-4444-5555-666677778888"
	default_product_grub_cfg = tmp_path / "grub.cfg"
	default_product_grub_cfg.write_text("default_grub_cfg: {{ linux.cmdline() }}", encoding="utf-8")
	grub_cfg_template = Path(tmp_path) / "template" / "grub.cfg"
	grub_cfg_template.parent.mkdir(parents=True, exist_ok=True)
	shutil.copy(Path("tests/data/grub.cfg"), grub_cfg_template)

	class MockServiceClient:
		updated_host: Host | None = None

		def host_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[Host]:
			if filter.get("id") == client_id:
				return [OpsiClient(id=client_id, systemUUID=system_uuid)]

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
					"clientconfig.configserver.url": ["https://service.opsi.test:4447/rpc"],
					"netboot.use_host_onetime_password": [True],
				}
			}

	mock_service_client = MockServiceClient()

	with (
		mock.patch("opsipxeconfd.opsipxeconfd.get_service_connection", return_value=mock_service_client),
		mock.patch("opsipxeconfd.template.get_service_connection", return_value=mock_service_client),
		mock.patch("opsipxeconfd.template.DEFAULT_PRODUCT_GRUB_CFG", str(default_product_grub_cfg)),
		mock.patch("opsipxeconfd.opsipxeconfd.PXE_CONFIG_DIR", str(tmp_path)),
		mock.patch("opsipxeconfd.get_depot_id", return_value=depot_id),
		mock.patch("opsipxeconfd.template.GRUB_CFG_TEMPLATE", str(grub_cfg_template)),
	):
		Opsipxeconfd({}).update_boot_configuration(client_id)

		assert isinstance(mock_service_client.updated_host, OpsiClient)

		data = (tmp_path / system_uuid).read_text(encoding="utf-8")
		assert "default_grub_cfg" in data
		match = re.search("otp=([a-z0-9]+)", data)
		assert match
		assert match.group(1) == mock_service_client.updated_host.oneTimePassword
