# -*- coding: utf-8 -*-

# This file is part of opsi.
# Copyright (C) 2020 uib GmbH <info@uib.de>

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
:copyright: uib GmbH <info@uib.de>
:license: GNU Affero General Public License version 3
"""

import os
import psutil
import getpass
import subprocess
from typing import Dict

from OPSI.Config import OPSI_ADMIN_GROUP, FILE_ADMIN_GROUP, DEFAULT_DEPOT_USER
from OPSI.setup import (
	setup_users_and_groups as po_setup_users_and_groups,
	get_users, get_groups, add_user_to_group, create_user
)
from OPSI.System.Posix import getLocalFqdn
from OPSI.Util.Task.Rights import setRights
from OPSI.Util.Task.InitializeBackend import initializeBackends
from OPSI.Backend.BackendManager import BackendManager

from opsicommon.logging import logger

"""
def setup_users_and_groups(config):
	logger.info("Setup users and groups")
	groups = get_groups()
	users = get_users()
	
	if config.run_as_user != "root":
		if config.run_as_user not in users:
			create_user(
				username=config.run_as_user,
				primary_groupname=FILE_ADMIN_GROUP,
				home="/var/lib/opsi",
				shell="/bin/bash",
				system=True
			)
			users = get_users()
		if "shadow" in groups and config.run_as_user not in groups["shadow"].gr_mem:
			add_user_to_group(config.run_as_user, "shadow")
		if OPSI_ADMIN_GROUP in groups and config.run_as_user not in groups[OPSI_ADMIN_GROUP].gr_mem:
			add_user_to_group(config.run_as_user, OPSI_ADMIN_GROUP)
"""

def setup_files(log_file : str) -> None:
	"""
	Setup for log file.

	This method creates a log file (and directories in its path if necessary).
	Afterwards permissions are set.

	:param log_file: Name and path of the logfile to set up.
	:type log_file: str
	"""
	logger.info("Setup files and permissions")
	log_dir = os.path.dirname(log_file)
	if not os.path.isdir(log_dir):
		os.makedirs(log_dir)
	setRights(log_dir)

def get_backend(config : Dict) -> BackendManager:
	"""
	Creates a BackendManager for current backend.

	This method extracts dispactConfig and backendConfig from
	an opsipxeconfd config dictionary and creates a BackendManager
	with respect to those.

	:param config: opsipxeconfd configuration dictionary as created by opsipxeconfdinit.
	:type config: Dict

	:returns: BackendManager for the given configuration
	:rtype: BackendManager
	"""
	bc = {
		'dispatchConfigFile': config['dispatchConfigFile'],
		'backendConfigDir': config['backendConfigDir'],
		###########'adminNetworks': config.admin_networks,
		'hostControlBackend': True,
		'hostControlSafeBackend': True,
		'depotBackend' : True
	}
	return BackendManager(**bc)


def setup_backend(config : Dict) -> None:
	"""
	Sets up the backend.

	This method retrieves a BackendManager for the current Backend and
	calls initializeBackends.

	:param config: opsipxeconfd configuration dictionary as created by opsipxeconfdinit.
	:type config: Dict
	"""
	fqdn = getLocalFqdn()
	try:
		backend = get_backend(config)
		depot = backend.host_getObjects(type='OpsiDepotserver', id=fqdn)
		if depot:
			return
	except Exception as e:
		logger.debug(e)
	
	logger.info("Setup backend")
	initializeBackends()

def setup(config : Dict) -> None:
	"""
	Setup method for opsipxeconfd.

	This method sets up the environment for the opsipxeconfd to run.
	It creates necessary users and groups, initializes the backend and log file.

	:param config: opsipxeconfd configuration dictionary as created by opsipxeconfdinit.
	:type config: Dict
	"""
	logger.notice("Running opsipxeconfd setup")
	po_setup_users_and_groups()
	#setup_users_and_groups(config)
	try:
		setup_backend(config)
	except Exception as e:
		logger.warning("Failed to setup backend: %s", e)
	setup_files(config['logFile'])
