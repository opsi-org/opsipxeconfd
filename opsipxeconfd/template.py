# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from jinja2 import Template
from jinja2.exceptions import UndefinedError
from opsicommon.logging import get_logger
from opsicommon.objects import NetbootProduct, OpsiClient, OpsiDepotserver, ProductOnClient, ProductOnDepot
from purecrypt import Method  # type: ignore[import]

from opsipxeconfd import DEFAULT_PRODUCT_GRUB_CFG, GRUB_CFG_TEMPLATE, LEGACY_PXE_CONFIG_DIR, PXE_CONFIG_DIR
from opsipxeconfd.service import get_service_connection
from opsipxeconfd.util import password_hash

SHADOW_HASH_RE = re.compile(r"^\$([a-z0-9]){1,2}\$(.+)\$(.+)$")

logger = get_logger()

template_cache: dict[str, tuple[Path, float, str]] = {}
template_cache_lock: Lock = Lock()


def read_grub_cfg(pxe_config_template: str | None = None) -> str:
	pxe_config_template = pxe_config_template or ""
	template_path: Path | None = None
	with template_cache_lock:
		cache = template_cache.get(pxe_config_template)
		if cache:
			template_path, mtime, data = cache
			try:
				if template_path.stat().st_mtime == mtime:
					return data
			except FileNotFoundError:
				pass

		if pxe_config_template:
			for path in Path(PXE_CONFIG_DIR), Path(LEGACY_PXE_CONFIG_DIR):
				cfg = path / pxe_config_template
				if cfg.exists():
					template_path = cfg
					break

			if not template_path:
				logger.error(
					"Grub config template file %r not found in %r or %r, using default template",
					pxe_config_template,
					PXE_CONFIG_DIR,
					LEGACY_PXE_CONFIG_DIR,
				)

		if not template_path:
			template_path = Path(DEFAULT_PRODUCT_GRUB_CFG)

		if not template_path.exists():
			logger.error("Grub config template %r not found", template_path)
			return ""

		logger.notice("Using grub config template file '%s'", template_path)

		data = template_path.read_text(encoding="utf-8")
		template_cache[pxe_config_template] = (template_path, template_path.stat().st_mtime, data)
		return data


@dataclass
class TemplateContextConfigState:
	id: str
	values: list[str | bool] = field(default_factory=list)
	_exists: bool = field(default=True, repr=False)

	@property
	def exists(self) -> bool:
		return self._exists

	@property
	def str_values(self) -> list[str]:
		return [str(v) for v in self.values]

	@property
	def bool_value(self) -> bool:
		return bool(self.value)

	@property
	def str_value(self) -> str:
		return str(self.value or "")

	@property
	def value(self) -> str | bool | None:
		if not self.values:
			return None
		if isinstance(self.values[0], bool):
			return self.values[0]
		return ",".join(str(v) for v in self.values)

	def __str__(self) -> str:
		if self.value is None:
			return ""
		return str(self.value)

	def __bool__(self) -> bool:
		if not self.exists:
			return False
		return bool(self.value)

	def password_hash(
		self, method: Literal["md5", "sha512", "pbkdf2-sha512"] = "sha512", format: Literal["shadow", "grub"] = "shadow"
	) -> str | None:
		value = self.value
		if not value or isinstance(value, bool):
			return None
		value = str(value)

		if format == "grub":
			if value.startswith("grub."):
				# Already hashed
				return value
		elif format == "shadow":
			match = SHADOW_HASH_RE.match(value)
			if match:
				if match.group(1) == str(Method.MD5.value) and method == "md5":
					return value
				if match.group(1) == str(Method.SHA512.value) and method == "sha512":
					return value
				raise ValueError(f"Password is already hashed with method {match.group(1)}, but {method} is requested")

		return password_hash(password=value, method=method, format=format)


class TemplateContextProductPropertyState(TemplateContextConfigState):
	pass


class TemplateContextConfigStates(dict[str, TemplateContextConfigState]):
	def __missing__(self, config_id: str) -> TemplateContextConfigState:
		return TemplateContextConfigState(id=config_id, _exists=False)

	def get_by_prefix(self, prefix: str) -> dict[str, TemplateContextConfigState]:
		return {key: value for key, value in self.items() if key.startswith(prefix)}


class TemplateContextProductPropertyStates(dict[str, TemplateContextProductPropertyState]):
	def __missing__(self, config_id: str) -> TemplateContextProductPropertyState:
		return TemplateContextProductPropertyState(id=config_id, _exists=False)

	def get_by_prefix(self, prefix: str) -> dict[str, TemplateContextProductPropertyState]:
		return {key: value for key, value in self.items() if key.startswith(prefix)}


@dataclass
class TemplateContextGrub:
	_context: TemplateContext
	primary_menu_entries: list[str] = field(default_factory=list)

	def menu_entries(self, config_id: str | None = None) -> list[str]:
		entries = self.primary_menu_entries
		grub_cfg = read_grub_cfg()
		if grub_cfg:
			entries.append(grub_cfg)
		if config_id:
			entries.extend([str(entry) for entry in self._context.config_states[config_id].values if entry])
		return [Template(entry).render(self._context.context_args()) for entry in entries]


@dataclass
class TemplateContextLinux:
	CMDLINE_PARAM_POSITION = {
		"quiet": 1,
		"splash": 2,
		"loglevel": 3,
	}
	_context: TemplateContext
	additional_cmdline_params: dict[str, str | bool] = field(default_factory=dict)

	def cmdline(self, config_id_prefix: str | None = None) -> str:
		"""
		Generate a Linux command line from config states starting with the given prefix.
		Additional command line parameters can be set in `additional_cmdline_params` and will override
		any config state with the same name.
		"""
		cmdline = [f"{key}={value}" if not isinstance(value, bool) else str(key) for key, value in self.additional_cmdline_params.items()]

		if "service" not in self.additional_cmdline_params:
			service = self._context.config_states["clientconfig.configserver.url"].str_value
			if service:
				if not service.endswith("/rpc"):
					# TODO: Is this still needed?
					service = f"{service.rstrip('/')}/rpc"
				cmdline.append(f"service={service}")

		if self._context.host and isinstance(self._context.host, OpsiClient):
			hostname, domain = self._context.host.id.split(".", 1)
			if "host_id" not in self.additional_cmdline_params:
				cmdline.append(f"host_id={self._context.host.id}")
			if "hn" not in self.additional_cmdline_params:
				cmdline.append(f"hn={hostname}")
			if "dn" not in self.additional_cmdline_params:
				cmdline.append(f"dn={domain}")
			if "macaddress" not in self.additional_cmdline_params and self._context.host.getHardwareAddress():
				cmdline.append(f"macaddress={self._context.host.getHardwareAddress()}")

		if self._context.product:
			if "product" not in self.additional_cmdline_params:
				cmdline.append(f"product={self._context.product.id}")

		if config_id_prefix:
			config_id_prefix = f"{config_id_prefix.rstrip('.')}."
			for key, config_state in self._context.config_states.get_by_prefix(config_id_prefix).items():
				param_name = key.removeprefix(config_id_prefix).lstrip(".")
				if param_name in self.additional_cmdline_params:
					continue
				if param_name == "pwh":
					pw_hash = config_state.password_hash("sha512", "shadow")
					if pw_hash:
						pw_hash = pw_hash.replace("$", r"\$")
						cmdline.append(f'{param_name}="{pw_hash}"')
					continue
				values = config_state.values
				if values and isinstance(values[0], bool):
					if values[0]:
						cmdline.append(param_name)
					continue
				vals = []
				for val in values:
					if not val:
						continue
					val = str(val)
					if " " in val or "," in val:
						val = f'"{val}"'
					vals.append(val)
				if vals:
					cmdline.append(f"{param_name}={','.join(vals)}")

		if "splash" in cmdline:
			cmdline = [param for param in cmdline if not param.startswith("loglevel=")]

		cmdline.sort(key=lambda param: self.CMDLINE_PARAM_POSITION.get(param.split("=", 1)[0], 99))

		return " ".join(cmdline)


@dataclass
class TemplateContextProduct:
	_context: TemplateContext
	_product: NetbootProduct

	def __getattr__(self, name: str) -> Any:
		return getattr(self._product, name)

	@property
	def product(self) -> NetbootProduct:
		return self._product

	def grub_cfg(self) -> str:
		logger.debug("Generating grub config for product '%s' (pxeConfigTemplate=%s)", self._product.id, self._product.pxeConfigTemplate)
		grub_cfg = self._product.pxeConfigTemplate or ""
		# Directly use the template if it contains newlines
		if "\n" in grub_cfg:
			logger.info("Using pxe config template directly from product '%s'", self._product.id)
			grub_cfg += "\n"
		else:
			pxe_config_template = grub_cfg if grub_cfg not in (None, "", "install3264", "install-x64") else ""
			if not pxe_config_template:
				logger.info("Using default grub config template file '%s' for product '%s'", DEFAULT_PRODUCT_GRUB_CFG, self._product.id)
			else:
				logger.info("Using pxe config template file '%s' from product '%s'", grub_cfg, self._product.id)
			grub_cfg = read_grub_cfg(pxe_config_template)

		try:
			context_args = self._context.context_args()
			grub_cfg = Template(grub_cfg).render(context_args)
		except UndefinedError as err:
			logger.error(
				"Error rendering grub config template for product '%s': %s\nTemplate:\n%s\nContext:\n%s",
				self._product.id,
				err,
				grub_cfg,
				context_args,
			)
			raise
		# Replace legacy placeholders
		hostname, domain = self._context.host.id.split(".", 1)
		grub_cfg = grub_cfg.replace("%fqdn%", self._context.host.id)
		grub_cfg = grub_cfg.replace("%host_id%", self._context.host.id)
		grub_cfg = grub_cfg.replace("%hostname%", hostname)
		grub_cfg = grub_cfg.replace("%domain%", domain)
		for property_name, state in self._context.product_property_states.items():
			grub_cfg = grub_cfg.replace(f"%{property_name}%", state.str_value)

		return grub_cfg


class TemplateContext:
	host: OpsiClient | OpsiDepotserver
	product: TemplateContextProduct | None
	product_on_depot: ProductOnDepot | None
	product_on_client: ProductOnClient | None
	product_property_states: TemplateContextProductPropertyStates
	config_states: TemplateContextConfigStates
	grub: TemplateContextGrub
	linux: TemplateContextLinux

	def __init__(
		self,
		host: OpsiClient | OpsiDepotserver,
		product_on_depot: ProductOnDepot | None = None,
		product_on_client: ProductOnClient | None = None,
		product: NetbootProduct | None = None,
	) -> None:
		self.host = host
		self.product = TemplateContextProduct(_context=self, _product=product) if product else None
		self.product_on_depot = product_on_depot
		self.product_on_client = product_on_client
		self.product_property_states = TemplateContextProductPropertyStates()
		self.config_states = TemplateContextConfigStates()
		self.grub = TemplateContextGrub(_context=self)
		self.linux = TemplateContextLinux(_context=self)

	def context_args(self) -> dict:
		return {attr: val for attr, val in self.__dict__.items() if not attr.startswith("_")}


def get_template_context(
	host: OpsiClient | OpsiDepotserver,
	product_on_depot: ProductOnDepot | None = None,
	product_on_client: ProductOnClient | None = None,
	product: NetbootProduct | None = None,
) -> TemplateContext:
	context = TemplateContext(
		host=host,
		product_on_depot=product_on_depot,
		product_on_client=product_on_client,
		product=product,
	)
	service = get_service_connection()
	context.config_states = TemplateContextConfigStates(
		{
			config_id: TemplateContextConfigState(id=config_id, values=values)
			for config_id, values in service.configState_getValues(  # type: ignore[attr-defined]
				config_ids=["clientconfig.configserver.url", "netboot.*"], object_ids=[host.id]
			)
			.get(host.id, {})
			.items()
		}
	)
	return context


def render_grub_cfg(context: TemplateContext) -> str:
	template = Template(Path(GRUB_CFG_TEMPLATE).read_text())
	return template.render(context.context_args())
