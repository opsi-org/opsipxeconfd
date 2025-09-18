# opsipxeconfd is part of the device management solution opsi http://www.opsi.org
# Copyright (c) 2013-2025 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0-only

import time
from unittest import mock

from opsicommon.messagebus.message import EventMessage

from opsipxeconfd import get_depot_id
from opsipxeconfd.service import get_messagebus_listener


def test_PXEConfigMessagebusListener() -> None:
	get_messagebus_listener.cache_clear()

	depot_id = get_depot_id()
	callback_calls = []

	def callback() -> None:
		nonlocal callback_calls
		callback_calls.append(time.time())

	with mock.patch("opsipxeconfd.service.GRUB_CFG_MAX_UPDATE_INTERVAL", 3):
		messagebus_listener = get_messagebus_listener()

	debouncer = messagebus_listener._netboot_config_changed_callback_debouncer
	messagebus_listener.set_netboot_config_changed_callback(callback)

	assert debouncer._num_triggered == 0
	assert debouncer._num_callbacks == 0

	messagebus_listener.message_received(
		EventMessage(
			sender="test",
			channel="event:config_updated",
			event="config_updated",
			data={"id": "netboot.test"},
		)
	)
	messagebus_listener.message_received(
		EventMessage(
			sender="test",
			channel="event:configState_created",
			event="configState_created",
			data={"configId": "netboot.test", "objectId": depot_id},
		)
	)
	# Unmatched configId
	messagebus_listener.message_received(
		EventMessage(
			sender="test",
			channel="event:config_updated",
			event="config_updated",
			data={"id": "other.config"},
		)
	)
	# Unmatched objectId
	messagebus_listener.message_received(
		EventMessage(
			sender="test",
			channel="event:configState_created",
			event="configState_created",
			data={"configId": "netboot.test", "objectId": "other.depot.id"},
		)
	)
	assert debouncer._num_triggered == 2
	assert debouncer._num_callbacks == 0
	time.sleep(5)
	assert debouncer._num_triggered == 2
	assert debouncer._num_callbacks == 1

	assert len(callback_calls) == 1

	messagebus_listener.message_received(
		EventMessage(
			sender="test",
			channel="event:config_deleted",
			event="config_deleted",
			data={"id": "netboot.test2"},
		)
	)
	assert debouncer._num_triggered == 3
	assert debouncer._num_callbacks == 1
	time.sleep(1)
	assert debouncer._num_triggered == 3
	assert debouncer._num_callbacks == 1
	time.sleep(5)
	assert debouncer._num_triggered == 3
	assert debouncer._num_callbacks == 2
	assert len(callback_calls) == 2

	debouncer.stop()
