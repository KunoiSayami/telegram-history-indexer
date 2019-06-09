# -*- coding: utf-8 -*-
# spider.py
# Copyright (C) 2019 KunoiSayami
#
# This module is part of telegram-history-helper and is released under
# the AGPL v3 License: https://www.gnu.org/licenses/agpl-3.0.txt
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
from pyrogram import Dialogs
import pyrogram.errors
import threading
import traceback
import time
from datetime import datetime, timezone
import logging

class iter_user_messages(threading.Thread):
	def __init__(self, indexer):
		threading.Thread.__init__(self, daemon = True)

		self.logger = logging.getLogger(__name__)
		self.logger.setLevel(logging.WARNING)

		self.client = indexer.client
		self.conn = indexer.conn
		self.indexer = indexer
		self.end_time = 0

	def run(self):
		self.get_dialogs()
		self.process_messages()

	def _indenify_user(self, users: list):
		userinfos = self.client.get_users(users)
		for x in userinfos:
			self.indexer.trackers.user_queue.put_nowait(x)
		self.conn.commit()

	def indenify_user(self):
		sqlObj = self.conn.query("SELECT `user_id` FROM `indexed_dialogs` WHERE `user_id` > 1")
		users = [x['user_id'] for x in sqlObj]
		while len(users) > 200:
			self._indenify_user(users[:200])
			users = users[200:]
		self._indenify_user(users)

	def get_dialogs(self):
		sqlObj = self.conn.query1("SELECT `last_message_id`, `indexed` FROM `indexed_dialogs` WHERE `user_id` = -1")
		if sqlObj is None:
			offset_date, switch = 0, True
		else:
			offset_date, switch = sqlObj['last_message_id'], sqlObj['indexed'] != 'Y'
		while switch:
			try:
				dialogs = self.client.get_dialogs(offset_date)
				self.process_dialogs(dialogs, sqlObj)
				time.sleep(3)
				offset_date = dialogs.dialogs[-1].top_message.date - 1
				sqlObj = self.conn.query1("SELECT `last_message_id`, `indexed` FROM `indexed_dialogs` WHERE `user_id` = -1")
			except pyrogram.errors.FloodWait as e:
				self.logger.warning('Caughted Flood wait, wait %d seconds', e.x)
				time.sleep(e.x)
			except IndexError:
				break
		if switch:
			self.indenify_user()
		self.logger.debug('Search over')

	def process_dialogs(self, dialogs: Dialogs, sqlObj: dict or None):
		for dialog in dialogs.dialogs:
			try:
				self.conn.execute("INSERT INTO `indexed_dialogs` (`user_id`, `last_message_id`) VALUE (%s, %s)", (dialog.chat.id, dialog.top_message.message_id))
			except:
				print(traceback.format_exc().splitlines()[-1])
			self.indexer.user_profile_track(dialog.top_message)
		try:
			if sqlObj:
				self.conn.execute("UPDATE `indexed_dialogs` SET `last_message_id` = %s WHERE `user_id` = -1", (dialogs.dialogs[-1].top_message.date - 1, ))
			else: # If None
				self.conn.execute("INSERT INTO `indexed_dialogs` (`user_id`, `last_message_id`) VALUE (%s, %s)", (-1, dialogs.dialogs[-1].top_message.date - 1))
		except IndexError:
			if sqlObj:
				self.conn.execute("UPDATE `indexed_dialogs` SET `indexed` = 'Y' WHERE `user_id` = -1")
			else:
				self.conn.execute("INSERT INTO `indexed_dialogs` (`user_id`,`indexed`, `last_message_id`) VALUE (-1, 'Y', 0)")
			raise
		finally:
			self.conn.commit()

	def process_messages(self):
		while True:
			sqlObj = self.conn.query1("SELECT * FROM `indexed_dialogs` WHERE `indexed` = 'N' AND `user_id` > 1 LIMIT 1")
			if sqlObj is None: break
			if self.conn.query1("SELECT * FROM `user_index` WHERE `user_id` = %s AND `is_bot` = 'Y'", (sqlObj['user_id'],)):
				self.conn.execute("UPDATE `indexed_dialogs` SET `indexed` = 'Y' WHERE `user_id` = %s", (sqlObj['user_id'],))
				continue
			self.conn.execute("UPDATE `indexed_dialogs` SET `started_indexed` = 'Y' WHERE `user_id` = %s", (sqlObj['user_id'],))
			self.conn.commit()
			self._process_messages(sqlObj['user_id'], sqlObj['last_message_id'])
			self.conn.execute("UPDATE `indexed_dialogs` SET `indexed` = 'Y' WHERE `user_id` = %s", (sqlObj['user_id'],))
			self.conn.commit()

	def _process_messages(self, user_id: int, offset_id: int, *, force_check: bool = False):
		while offset_id > 1:
			self.logger.debug('Current process %d %d',user_id, offset_id)
			while True:
				try:
					msg_his = self.client.get_history(user_id, offset_id = offset_id)
					break
				except pyrogram.errors.FloodWait as e:
					self.logger.warning('got FloodWait, wait %d seconds', e.x)
					time.sleep(e.x)
			if self.__process_messages(msg_his.messages, force_check):
				break
			try:
				offset_id = msg_his.messages[-1].message_id - 1
			except IndexError:
				break
			time.sleep(3)

	def __process_messages(self, msg_group: list, force_check: bool = False):
		for x in msg_group:
			if force_check: x.edit_date = 0
			self.indexer.trackers.msg_queue.put_nowait(x)
			if x.date < self.end_time:
				return True
		return

	def recheck(self, force_check: bool = False):
		sqlObj = self.conn.query1("SELECT `timestamp` FROM `index` ORDER BY `timestamp` DESC LIMIT 1")
		self.logger.debug('Rechecking...')
		if force_check or (sqlObj and (datetime.now() - sqlObj['timestamp']).total_seconds() > 60 * 30):
			if isinstance(self.end_time, int) and self.end_time == 0:
				self.end_time = sqlObj['timestamp'].replace(tzinfo=timezone.utc).timestamp()
			if isinstance(self.end_time, datetime):
				self.end_time = self.end_time.replace(tzinfo=timezone.utc).timestamp()

			self.logger.info('Calling recheck function')
			self.logger.debug('Endtime is %d', self.end_time)

			threading.Thread(target = self._recheck, daemon = True).start()

			self.logger.debug('Recheck function start successful')
		else:
			self.logger.info('Nothing to recheck')

	def _recheck(self):
		while not self.client.is_started: time.sleep(0.01)
		offset_date = 0
		chats = []
		while True:
			try:
				dialogs = self.client.get_dialogs(offset_date)
				for x in dialogs.dialogs:
					if x.top_message.date < self.end_time:
						raise IndexError
					chats.append((x.chat.id, x.top_message.message_id))
				offset_date = dialogs.dialogs[-1].top_message.date - 1
			except pyrogram.errors.FloodWait as e:
				self.logger.warning('Caughted Flood wait, wait %d seconds', e.x)
				time.sleep(e.x)
			except IndexError:
				break
		self.logger.info('Find %d chats', len(chats))
		self.logger.debug('chats (%s)', repr(chats))
		for x in chats:
			self._process_messages(x[0], x[1], force_check = True)