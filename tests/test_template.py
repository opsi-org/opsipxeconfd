# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

import shutil
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest
from opsicommon.objects import NetbootProduct, OpsiClient

from opsipxeconfd.template import TemplateContext, TemplateContextConfigState, TemplateContextConfigStates, render_grub_cfg


def test_TemplateContextConfigStates() -> None:
	states = TemplateContextConfigStates()
	states["netboot.host_identifiers"] = TemplateContextConfigState(id="netboot.host_identifiers", values=["mac", "uuid"])
	assert states["netboot.host_identifiers"]
	assert states["netboot.host_identifiers"].exists
	assert states["netboot.host_identifiers"].value == "mac,uuid"

	# Missing entries return a default TemplateContextConfigState
	assert not states["missing"]
	assert states["missing"].exists is False
	assert states["missing"].value is None
	assert states["missing"].password_hash() is None
	assert str(states["missing"]) == ""

	# But we can set values later
	states["missing"] = TemplateContextConfigState(id="missing", values=[True])
	assert states["missing"]
	assert states["missing"].exists
	assert states["missing"].value is True
	assert states["missing"].password_hash() is None
	assert str(states["missing"]) == "True"


def test_TemplateContextConfigState_password_hash() -> None:
	state = TemplateContextConfigState(id="netboot.grub.password", values=["secret"], _is_password=True)

	pw_hash_md5 = state.password_hash("md5")
	assert pw_hash_md5
	assert pw_hash_md5.startswith("$1$")  # MD5

	pw_hash_sha512 = state.password_hash("sha512")
	assert pw_hash_sha512
	assert pw_hash_sha512.startswith("$6$")  # SHA-512

	state.values = [pw_hash_md5]
	with pytest.raises(ValueError, match="Password is already hashed with method 1, but sha512 is requested"):
		state.password_hash("sha512")


def test_TemplateContext_linux_cmdline() -> None:
	context = TemplateContext(host=OpsiClient(id="client1.opsi.test"))
	context.config_states["clientconfig.configserver.url"] = TemplateContextConfigState(
		id="clientconfig.configserver.url", values=["http://opsi.test:4447/rpc"]
	)
	context.config_states["netboot.linux-bootimage.cmdline.option1"] = TemplateContextConfigState(
		id="netboot.linux-bootimage.cmdline.option1",
		values=["", None],  # type: ignore
	)
	context.config_states["netboot.linux-bootimage.cmdline.sub1.sub2.option2"] = TemplateContextConfigState(
		id="netboot.linux-bootimage.cmdline.sub1.sub2.option2",
		values=[],
	)
	context.config_states["netboot.linux-bootimage.cmdline.option3"] = TemplateContextConfigState(
		id="netboot.linux-bootimage.cmdline.option3", values=[True]
	)
	context.config_states["netboot.linux-bootimage.cmdline.option4"] = TemplateContextConfigState(
		id="netboot.linux-bootimage.cmdline.option4", values=[False]
	)
	context.config_states["netboot.linux-bootimage.cmdline.option5"] = TemplateContextConfigState(
		id="netboot.linux-bootimage.cmdline.option5", values=["value with spaces", "value,with,commas"]
	)
	context.config_states["netboot.linux-bootimage.cmdline.sub1.option6"] = TemplateContextConfigState(
		id="netboot.linux-bootimage.cmdline.sub1.option6", values=["1", "value2"]
	)

	assert context.linux.cmdline() == "service=http://opsi.test:4447/rpc host_id=client1.opsi.test hn=client1 dn=opsi.test"
	kernel_cmdline = context.linux.cmdline("netboot.linux-bootimage.cmdline")
	assert kernel_cmdline == (
		"service=http://opsi.test:4447/rpc host_id=client1.opsi.test hn=client1 dn=opsi.test "
		'option1 sub1.sub2.option2 option3 option5="value with spaces","value,with,commas" sub1.option6=1,value2'
	)

	# additional_params override config states
	context.linux.additional_cmdline_params = {"option1": "value1", "sub1.option6": "overridden"}
	assert (
		context.linux.cmdline()
		== "option1=value1 sub1.option6=overridden service=http://opsi.test:4447/rpc host_id=client1.opsi.test hn=client1 dn=opsi.test"
	)
	assert context.linux.cmdline("netboot.linux-bootimage.cmdline") == (
		"option1=value1 sub1.option6=overridden service=http://opsi.test:4447/rpc host_id=client1.opsi.test hn=client1 dn=opsi.test "
		'sub1.sub2.option2 option3 option5="value with spaces","value,with,commas"'
	)

	# Test other prefix
	context.config_states["some.prefix.option1"] = TemplateContextConfigState(id="some.prefix.option1", values=[False])
	context.config_states["some.prefix.sub1.option2"] = TemplateContextConfigState(id="some.prefix.sub1.option2", values=["r", "f"])
	kernel_cmdline = context.linux.cmdline()
	assert (
		kernel_cmdline
		== "option1=value1 sub1.option6=overridden service=http://opsi.test:4447/rpc host_id=client1.opsi.test hn=client1 dn=opsi.test"
	)
	kernel_cmdline = context.linux.cmdline("some.prefix")
	assert (
		kernel_cmdline
		== "option1=value1 sub1.option6=overridden service=http://opsi.test:4447/rpc host_id=client1.opsi.test hn=client1 dn=opsi.test sub1.option2=r,f"
	)


def test_TemplateContext_grub_menu_entries() -> None:
	context = TemplateContext(host=OpsiClient(id="client1.opsi.test"))
	context.config_states["netboot.grub.additional_menu_entries"] = TemplateContextConfigState(
		id="netboot.grub.additional_menu_entries",
		values=["menuentry 'Entry 1' { echo '{{host.id}}'; }", "menuentry 'Entry 2' { echo 'Entry 2'; }"],
	)
	context.grub.primary_menu_entries = [
		"menuentry 'Primary Entry' { echo '{{host.id}}'; }",
		"menuentry 'Secondary Entry' { echo 'Secondary Entry'; }",
	]
	entries = context.grub.menu_entries()
	assert len(entries) == 2
	assert entries[0] == "menuentry 'Primary Entry' { echo 'client1.opsi.test'; }"
	assert entries[1] == "menuentry 'Secondary Entry' { echo 'Secondary Entry'; }"

	entries = context.grub.menu_entries("netboot.grub.additional_menu_entries")
	assert len(entries) == 4
	assert entries[0] == "menuentry 'Primary Entry' { echo 'client1.opsi.test'; }"
	assert entries[1] == "menuentry 'Secondary Entry' { echo 'Secondary Entry'; }"
	assert entries[2] == "menuentry 'Entry 1' { echo 'client1.opsi.test'; }"
	assert entries[3] == "menuentry 'Entry 2' { echo 'Entry 2'; }"


def test_render_grub_cfg(tmp_path: Path) -> None:
	grub_cfg_template = Path(tmp_path) / "grub.cfg"
	shutil.copy(Path("tests/data/grub.cfg"), grub_cfg_template)

	pxe_config_template = dedent("""
		menuentry 'Start netboot for {{ product.name }}' {
			linux (pxe)/opsi/opsi-linux-bootimage/kernel.x64 {{ linux.cmdline("netboot.linux-bootimage.cmdline") }}
		}
	""")
	context = TemplateContext(
		host=OpsiClient(id="client1.opsi.test"),
		product=NetbootProduct(
			id="test_product", productVersion="1.0", packageVersion="1", name="Test Product", pxeConfigTemplate=pxe_config_template
		),
	)
	context.host = OpsiClient(id="client1.opsi.test")
	context.config_states["netboot.grub.graphicsmode"] = TemplateContextConfigState(id="netboot.grub.graphicsmode", values=[True])
	context.config_states["netboot.grub.password"] = TemplateContextConfigState(
		id="netboot.grub.password", values=["secret"], _is_password=True
	)
	context.config_states["netboot.grub.timeout"] = TemplateContextConfigState(id="netboot.grub.timeout", values=["9"])
	context.config_states["netboot.linux-bootimage.cmdline.option1"] = TemplateContextConfigState(
		id="netboot.linux-bootimage.cmdline.option1", values=[True]
	)
	context.config_states["netboot.grub.additional_menu_entries"] = TemplateContextConfigState(
		id="netboot.grub.additional_menu_entries",
		values=[
			"menuentry 'Entry 1' { echo '{{host.id}}'; }",
			'if [ "$grub_platform" = "efi" ]; then menuentry \'efi\' { echo "efi" }; fi',
		],
	)
	context.grub.primary_menu_entries = ["menuentry 'Primary Entry' { echo '{{host.id}}'; }"]
	context.linux.additional_cmdline_params = {"hn": "client1", "dn": "opsi.test"}

	with patch("opsipxeconfd.template.GRUB_CFG_TEMPLATE", str(grub_cfg_template)):
		data = render_grub_cfg(context)
		assert 'echo "grub.cfg"' in data
		assert 'echo "gfxmode"' in data
		assert 'echo "password: $1$' in data
		assert (
			dedent("""
			menuentry 'Start netboot for Test Product' {
				linux (pxe)/opsi/opsi-linux-bootimage/kernel.x64 hn=client1 dn=opsi.test host_id=client1.opsi.test product=test_product option1
			}
			""")
			in data
		)

		context.config_states["netboot.grub.graphicsmode"].values = [False]
		context.product = None
		data = render_grub_cfg(context)
		assert 'echo "gfxmode"' not in data
		assert "set timeout=9" in data
		assert (
			dedent("""
			menuentry 'Local Disk' {
				echo "Local Disk"
			}
			""")
			in data
		)
		assert 'if [ "$grub_platform" = "efi" ]; then menuentry \'efi\' { echo "efi" }; fi' in data
		assert "menuentry 'Primary Entry' { echo 'client1.opsi.test'; }" in data
		assert "menuentry 'Entry 1' { echo 'client1.opsi.test'; }" in data


def test_product_grub_cfg(tmp_path: Path) -> None:
	pxe_config_dir = tmp_path / "cfg"
	legacy_pxe_config_dir = tmp_path / "legacy_cfg"
	default_product_grub_cfg = tmp_path / "grub.cfg"
	template_desinfect = pxe_config_dir / "desinfect"
	legacy_template_igel = legacy_pxe_config_dir / "igel"

	pxe_config_dir.mkdir()
	legacy_pxe_config_dir.mkdir()
	template_desinfect.write_text("template_desinfect: {{host.id}} - {{product.id}}", encoding="utf-8")
	legacy_template_igel.write_text("legacy_template_igel: {{host.id}} - {{product.id}}", encoding="utf-8")
	default_product_grub_cfg.write_text("default_product_grub_cfg: {{host.id}} - {{product.id}}", encoding="utf-8")

	orig_read_text = Path.read_text

	read_text_called = 0

	def read_text(self: Path, encoding: str | None = None, errors: str | None = None, newline: str | None = None) -> str:
		nonlocal read_text_called
		read_text_called += 1
		return orig_read_text(self, encoding=encoding, errors=errors, newline=newline)

	with (
		patch("opsipxeconfd.template.PXE_CONFIG_DIR", str(pxe_config_dir)),
		patch("opsipxeconfd.template.LEGACY_PXE_CONFIG_DIR", str(legacy_pxe_config_dir)),
		patch("opsipxeconfd.template.DEFAULT_PRODUCT_GRUB_CFG", str(default_product_grub_cfg)),
		patch("opsipxeconfd.template.Path.read_text", read_text),
	):
		for iteration in range(3):
			read_text_called = 0
			if iteration == 2:
				template_desinfect.write_text("template_desinfect_modified: {{host.id}} - {{product.id}}", encoding="utf-8")
				default_product_grub_cfg.write_text("default_product_grub_cfg_modified: {{host.id}} - {{product.id}}", encoding="utf-8")

			# Product with specific template in PXE_CONFIG_DIR
			context = TemplateContext(
				host=OpsiClient(id="client1.opsi.test"),
				product=NetbootProduct(
					id="desinfect", productVersion="1.0", packageVersion="1", name="Desinfect", pxeConfigTemplate="desinfect"
				),
			)
			assert context.product
			assert (
				context.product.grub_cfg()
				== f"{'template_desinfect_modified' if iteration == 2 else 'template_desinfect'}: client1.opsi.test - desinfect"
			)

			# Product with specific template in LEGACY_PXE_CONFIG_DIR
			context = TemplateContext(
				host=OpsiClient(id="client1.opsi.test"),
				product=NetbootProduct(id="igel", productVersion="1.0", packageVersion="1", name="Igel", pxeConfigTemplate="igel"),
			)
			assert context.product
			assert context.product.grub_cfg() == "legacy_template_igel: client1.opsi.test - igel"

			# Product without specific template uses DEFAULT_PRODUCT_GRUB_CFG
			context = TemplateContext(host=OpsiClient(id="client1.opsi.test"))
			for pxe_config_template in (None, "", "install3264", "install-x64"):
				context = TemplateContext(
					host=OpsiClient(id="client1.opsi.test"),
					product=NetbootProduct(
						id="product1",
						productVersion="1.0",
						packageVersion="1",
						name="Product 1",
						pxeConfigTemplate=pxe_config_template,  # type: ignore
					),
				)
				assert context.product
				assert (
					context.product.grub_cfg()
					== f"{'default_product_grub_cfg_modified' if iteration == 2 else 'default_product_grub_cfg'}: client1.opsi.test - product1"
				)

			if iteration == 0:
				# Cache empty
				assert read_text_called == 3
			elif iteration == 1:
				# Cache hits
				assert read_text_called == 0
			else:
				# Two template files modified, so two cache misses
				assert read_text_called == 2
