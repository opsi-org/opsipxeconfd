#! /usr/bin/env python
# -*- coding: utf-8 -*-

# This file is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2019 uib GmbH <info@uib.de>
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

import codecs
import os.path
from setuptools import setup


with codecs.open(os.path.join("debian", "changelog"), 'r', 'utf-8') as changelog:
	VERSION = changelog.readline().split('(')[1].split('-')[0]

if not VERSION:
	raise ValueError(u"Failed to get version info")

# Always set __version__ to the version found in the changelog to make
# sure the version is always up-to-date  and nobody needs to manually
# update it.
initFilePath = os.path.join('opsipxeconfd')
newInitLines = []
with open(initFilePath) as originalFile:
	for line in originalFile:
		if line.startswith('__version__'):
			newInitLines.append("__version__ = '{0}'\n".format(VERSION))
			continue

		newInitLines.append(line)

with open(initFilePath, 'w') as newInitFile:
	newInitFile.writelines(newInitLines)
print("Patched version {1!r} from changelog into {0}".format(initFilePath, VERSION))


setup(
	name='opsipxeconfd',
	version=VERSION,
	license='AGPL-3',
	url="http://www.opsi.org",
	description='The opsi pxe configiration management daemon',
	scripts=['opsipxeconfd'],
	data_files=[
		('/etc/opsi', ['data/etc/opsi/opsipxeconfd.conf']),
		('/etc/logrotate.d', ['data/etc/logrotate.d/opsipxeconfd']),
	],
)
