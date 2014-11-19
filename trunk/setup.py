#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
   =   opsi pxe configuration daemon (opsipxeconfd) setup file   =
   = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =

   opsiconfd is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org

   Copyright (C) 2010 uib GmbH

   http://www.uib.de/

   All rights reserved.

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License version 2 as
   published by the Free Software Foundation.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program; if not, write to the Free Software
   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

   @copyright:	uib GmbH <info@uib.de>
   @author: Christian Kampka <c.kampka@uib.de>
   @license: GNU General Public License version 2
"""

from setuptools import setup

cmdclass = {}

try:
	from opsidistutils.commands.osc_cmd import osc_publish as osc
	cmdclass['osc'] = osc
except ImportError:
	print "osc integration is not available on this machine. please install ospi-distutils."

version = None
f = open("scripts/opsipxeconfd")
for line in f.readlines():
	if (line.find('__version__') != -1):
		version = line.split('=')[1].strip()
		break
f.close()

setup(
	name='opsipxeconfd',
	version=version,
	license='GPL-2',
	url="http://www.opsi.org",
	description='The opsi pxe configiration management daemon',
	#long-description='Long description goes here',
	scripts=['scripts/opsipxeconfd'],
	data_files=[('/etc/opsi', ['data/etc/opsi/opsipxeconfd.conf']),
		    ('/etc/init.d', ['data/etc/init.d/opsipxeconfd']),
		    ('/etc/logrotate.d', ['data/etc/logrotate.d/opsipxeconfd']),
		   ],
	cmdclass=cmdclass
)

