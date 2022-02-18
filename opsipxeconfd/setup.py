# -*- coding: utf-8 -*-

# opsipxeconfd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2013-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

"""
opsipxeconfd - setup
"""

import os
from typing import Dict

from OPSI.setup import setup_users_and_groups as po_setup_users_and_groups
from OPSI.System.Posix import getLocalFqdn
from OPSI.Util.Task.Rights import setRights
from OPSI.Util.Task.InitializeBackend import initializeBackends
from OPSI.Backend.BackendManager import BackendManager

from opsicommon.logging import logger


def setup_files(log_file: str) -> None:
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


def get_backend(config: Dict) -> BackendManager:
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
		"dispatchConfigFile": config["dispatchConfigFile"],
		"backendConfigDir": config["backendConfigDir"],
		"hostControlBackend": True,
		"hostControlSafeBackend": True,
		"depotBackend": True,
	}
	return BackendManager(**bc)


def setup_backend(config: Dict) -> None:
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
		depot = backend.host_getObjects(type="OpsiDepotserver", id=fqdn)  # pylint: disable=no-member
		if depot:
			return
	except Exception as err:  # pylint: disable=broad-except
		logger.debug(err)

	logger.info("Setup backend")
	initializeBackends()


def setup(config: Dict) -> None:
	"""
	Setup method for opsipxeconfd.

	This method sets up the environment for the opsipxeconfd to run.
	It creates necessary users and groups, initializes the backend and log file.

	:param config: opsipxeconfd configuration dictionary as created by opsipxeconfdinit.
	:type config: Dict
	"""
	logger.notice("Running opsipxeconfd setup")
	po_setup_users_and_groups()
	try:
		setup_backend(config)
	except Exception as err:  # pylint: disable=broad-except
		logger.warning("Failed to setup backend: %s", err)
	setup_files(config["logFile"])
