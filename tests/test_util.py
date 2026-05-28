# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

import os
from pathlib import Path

from opsipxeconfd.util import pid_file


def test_pid_file(tmp_path: Path) -> None:
	pid_file_path = tmp_path / "pidfile.pid"
	with pid_file(pid_file_path):
		assert pid_file_path.read_text(encoding="utf-8").strip() == str(os.getpid())
	assert not pid_file_path.exists()
