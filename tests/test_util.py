# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

import os
from pathlib import Path
from unittest import mock

from opsipxeconfd.setup import password_hash
from opsipxeconfd.util import pid_file


def test_pid_file(tmp_path: Path) -> None:
	pid_file_path = tmp_path / "pidfile.pid"
	with pid_file(pid_file_path):
		assert pid_file_path.read_text(encoding="utf-8").strip() == str(os.getpid())
	assert not pid_file_path.exists()


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
