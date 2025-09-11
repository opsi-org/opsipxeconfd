# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

import sys
from pathlib import Path
from unittest import mock

from opsipxeconfd.opsipxeconfdinit import OpsipxeconfdInit


def test_process_config(tmp_path: Path) -> None:
	conf_file = tmp_path / "opsipxeconfd.conf"
	conf_file.write_text("max control connections = 50\n")
	with mock.patch.object(sys, "argv", ["opsipxeconfd", "-c", str(conf_file), "setup"]):
		init = OpsipxeconfdInit()
		init.process_config()
		assert init.config["maxConnections"] == 50
