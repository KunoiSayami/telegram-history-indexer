# -*- coding: utf-8 -*-
# task.py
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
from queue import Queue
from libpy3.mysqldb import mysqldb
from threading import Thread
from pyrogram import Client, Message, User, Chat
import time
import datetime
import traceback
import threading
from type_user import user_profile
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

class fake_notify_class(object):
	def send(self):
		pass

class notify_class(object):
	def __init__(self, client: Client, target: int, interval: int = 60):
		self.client = client
		self.target = target
		self.interval = interval
		self.last_send = time.time()
	def send(self, msg: str):
		if time.time() - self.last_send < self.interval:
			return False
		try:
			self.client.send_message(self.target, f'```{msg}```')
		except:
			traceback.print_exc()
		finally:
			self.last_send = time.time()
		return True

class msg_tracker_thread_class(Thread):
	def __init__(self, client: Client, conn: mysqldb, filter_func: 'callable', *, notify: notify_class = None, other_client: Client = None):
		Thread.__init__(self, daemon = True)

		self.msg_queue = Queue()
		self.user_queue = Queue()
		self.client = client
		self.conn = conn
		self.other_client = other_client
		self.filter_func = filter_func
		if self.other_client is None:
			self.other_client = self.client
		self.notify = notify
		if self.notify is None:
			self.notify = fake_notify_class()

	def start(self):
		logger.debug('Starting `msg_tracker_thread_class\'')
		Thread(target = self.user_tracker, daemon = True).start()
		threading.Thread.start(self)
		logger.debug('Start `msg_tracker_thread_class\' successful')

	def run(self):
		logger.debug('`msg_tracker_thread\' started!')
		while not self.client.is_started: time.sleep(0.5)
		while True:
			while self.msg_queue.empty():
				time.sleep(0.1)
			self.filter_msg()
			self.conn.commit()

	def _filter_msg(self, msg: Message):
		text = msg.text if msg.text else msg.caption if msg.caption else ''

		if text.startswith('/') and not text.startswith('//'):
			return
		
		_type = self.get_msg_type(msg)
		if _type == 'error':
			if text == '': return
			else:
				_type = 'text'
		
		if msg.edit_date:
			sqlObj = self.conn.query1("SELECT `_id`, `text` FROM `{}index` WHERE `chat_id` = %s AND `message_id` = %s".format(
					'document_' if _type != 'text' else ''
				), (msg.chat.id, msg.message_id))
			if sqlObj is not None:
				if text == sqlObj['text']: return
				self.conn.execute("UPDATE `{}index` SET `text` = %s WHERE `_id` = %s".format(
						'document_' if _type != 'text' else ''
					), (text, sqlObj['_id']))
				return

		self.conn.execute(
			"INSERT INTO `index` (`chat_id`, `message_id`, `from_user`, `forward_from`, `text`, `timestamp`) VALUE (%s, %s, %s, %s, %s, %s)",
			(
				msg.chat.id,
				msg.message_id,
				msg.from_user.id if msg.from_user else msg.chat.id,
				msg.forward_from.id if msg.forward_from else msg.forward_from_chat.id if msg.forward_from_chat else None,
				text,
				datetime.datetime.fromtimestamp(msg.date)
			)
		)
		if _type != 'text':
			self.conn.execute(
				"INSERT INTO `document_index` (`chat_id`, `message_id`, `from_user`, `forward_from`, `text`, `timestamp`, `type`, `file_id`) "
					"VALUE (%s, %s, %s, %s, %s, %s, %s, %s)", (
						msg.chat.id,
						msg.message_id,
						msg.from_user.id if msg.from_user else msg.chat.id,
						msg.forward_from.id if msg.forward_from else msg.forward_from_chat.id if msg.forward_from_chat else None,
						text if len(text) > 0 else None,
						datetime.datetime.fromtimestamp(msg.date),
						_type,
						self.get_file_id(msg, _type)
				)
			)
		logger.debug('INSERT INTO `index` %d %d %s', msg.chat.id, msg.message_id, text)

	def filter_msg(self):
		while not self.msg_queue.empty():
			msg = self.msg_queue.get_nowait()
			if self.filter_func(msg): continue
			try:
				self._filter_msg(msg)
			except:
				self.notify.send(traceback.format_exc())
				traceback.print_exc()

	def user_tracker(self):
		logger.debug('`user_tracker\' started!')
		while not self.client.is_started: time.sleep(0.5)
		while True:
			while self.user_queue.empty():
				time.sleep(0.1)
			self._user_tracker()
			self.conn.commit()

	def _user_tracker(self):
		while not self.user_queue.empty():
			self._real_user_index(self.user_queue.get_nowait())

	def insert_username(self, user: User or Chat):
		if user.username is None:
			return
		sqlObj = self.conn.query1("SELECT `username` FROM `username_history` WHERE `user_id` = %s ORDER BY `_id` DESC LIMIT 1", (user.id,))
		if sqlObj and sqlObj['username'] == user.username:
			return
		self.conn.execute("INSERT INTO `username_history` (`user_id`, `username`) VALUE (%s, %s)", (user.id, user.username))
		self.conn.commit()

	def _real_user_index(self, user: User or Chat, *, enable_request: bool = False):
		self.insert_username(user)
		sqlObj = self.conn.query1("SELECT * FROM `user_index` WHERE `user_id` = %s", user.id)
		profileObj = user_profile(user)
		if sqlObj is None:
			is_bot = isinstance(user, User) and user.is_bot
			is_group = user.id < 0
			self.conn.execute(
				"INSERT INTO `user_index` (`user_id`, `first_name`, `last_name`, `photo_id`, `hash`, `is_bot`, `is_group`) VALUE (%s, %s, %s, %s, %s, %s, %s)",
				(
					profileObj.user_id,
					profileObj.first_name,
					profileObj.last_name,
					profileObj.photo_id,
					profileObj.hash,
					'Y' if is_bot else 'N',
					'Y' if is_group else 'N'
				)
			)
			self.conn.execute(*profileObj.sql_insert)
			return True
		elif profileObj.hash != sqlObj['hash']:
			self.conn.execute(
				"UPDATE `user_index` SET `first_name` = %s, `last_name` = %s, `photo_id` = %s, `hash` = %s, `timestamp` = CURRENT_TIMESTAMP() WHERE `user_id` = %s",
				(
					profileObj.first_name,
					profileObj.last_name,
					profileObj.photo_id,
					profileObj.hash,
					profileObj.user_id,
				)
			)
			self.conn.execute(*profileObj.sql_insert)
			return True
		elif enable_request and (datetime.datetime.now() - sqlObj['last_refresh']).total_seconds() > 3600:
			if isinstance(user, User):
				u = self.client.get_users([user.id,])[0]
			else:
				u = self.client.get_chat(user.id)
			self.conn.execute('UPDATE `user_index` SET `last_refresh` = CURRENT_TIMESTAMP() WHERE `user_id` = %s', user.id)
			return self._real_user_index(u)
		return False

	def push(self, msg: Message):
		self.msg_queue.put_nowait(msg)
		users = [x.raw for x in list(set(user_profile(x) for x in [msg.from_user, msg.chat, msg.forward_from, msg.forward_from_chat, msg.via_bot]))]
		users.remove(None)
		for x in users:
			self.user_queue.put_nowait(x)

	@staticmethod
	def get_msg_type(msg: Message):
		return 'photo' if msg.photo else \
			'video' if msg.video else \
			'animation' if msg.animation else \
			'document' if msg.document else \
			'text' if msg.text else \
			'voice' if msg.voice else'error'
	
	@staticmethod
	def get_file_id(msg: Message, _type: str):
		if _type == 'photo':
			return msg.photo.sizes[-1].file_id
		else:
			return getattr(msg, _type).file_id