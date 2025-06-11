import grp
import os
import pwd
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def set_tmp_path(tmp_path: Path) -> Generator[None, None, None]:
	opsi_conf = tmp_path / "opsi.conf"

	primary_group_name = grp.getgrgid(pwd.getpwuid(os.getuid()).pw_gid).gr_name
	opsi_conf.write_text(f'[groups]\nadmingroup = "{primary_group_name}"\n')

	@contextmanager
	def mock_pid_file(pid_file_path: str) -> Generator[None, None, None]:
		# Mock function to avoid actual file operations
		yield

	with (
		patch("opsicommon.config.OpsiConfig.config_file", opsi_conf),
		patch("opsipxeconfd.opsipxeconfdinit.pid_file", mock_pid_file),
		patch("opsipxeconfd.opsipxeconfdinit.init_logging", lambda config: None),
		patch("opsipxeconfd.opsipxeconfdinit.setup", lambda config: None),
		patch("opsipxeconfd.opsipxeconfdinit.OpsipxeconfdInit.daemonize", lambda self: None),
	):
		yield
