#! /usr/bin/env python
# -*- coding: utf-8 -*-

# This file is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2015 uib GmbH <info@uib.de>
# All rights reserved.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
opsi pxe configuration daemon (opsipxeconfd) setup file

:copyright: uib GmbH <info@uib.de>
:author: Christian Kampka <c.kampka@uib.de>
:license: GNU Affero General Public License version 3
"""

from setuptools import setup


with open("scripts/opsipxeconfd") as f:
	for line in f.readlines():
		if line.startswith('__version__'):
			version = line.split('=')[1].strip()
			break
	else:
		version = None

setup(
	name='opsipxeconfd',
	version=version,
	license='AGPL-3',
	url="http://www.opsi.org",
	description='The opsi pxe configiration management daemon',
	scripts=['scripts/opsipxeconfd'],
	data_files=[
		('/etc/opsi', ['data/etc/opsi/opsipxeconfd.conf']),
		('/etc/init.d', ['data/etc/init.d/opsipxeconfd']),
		('/etc/logrotate.d', ['data/etc/logrotate.d/opsipxeconfd']),
	],
)
