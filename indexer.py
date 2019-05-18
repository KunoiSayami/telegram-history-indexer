# -*- coding: utf-8 -*-
# indexer.py
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
import subprocess
from libpy3.mysqldb import mysqldb
import json
from configparser import ConfigParser
from pyrogram import Client, Message, User, MessageHandler, Chat, Filters
import hashlib
import warnings
import traceback
import threading
import datetime
from index_bothelper import bot_search_helper

class user_profile(object):
	def __init__(self, user: User or Chat or None):
		self.user_id = user.id
		#self.username = user.username if user.username else None
		self.photo_id = user.photo.big_file_id if user.photo else None
		self._photo_id = self.photo_id if self.photo_id else ''

		if isinstance(user, Chat) and user.type != 'private':
			self.full_name = user.title
		else:
			self.first_name = user.first_name
			self.last_name = user.last_name if user.last_name else None
			self.full_name = '{} {}'.format(self.first_name, self.last_name) if self.last_name else self.first_name

		self.hash = hashlib.sha256(','.join((
			str(self.user_id),
			#self.username if self.username else '',
			self.full_name,
			self.photo_id if self.photo_id else ''
		)).encode()).hexdigest()

		if isinstance(user, User):
			self.sql_insert = (
				"INSERT INTO `user_history` (`user_id`, `first_name`, `last_name`, `photo_id`, `hash`) VALUES (%s, %s, %s, %s, %s)",
				(
					self.user_id,
					#self.username,
					self.first_name,
					self.last_name,
					self.photo_id,
					self.hash
				)
			)
		else:
			self.sql_insert = (
				"INSERT INTO `user_history` (`user_id`, `first_name` , `photo_id`, `hash`) VALUES (%s, %s, %s, %s)",
				(
					self.user_id,
					#self.username,
					self.full_name,
					self.photo_id,
					self.hash
				)
			)

class history_index_class(object):
	def __init__(self, client: Client = None, conn: mysqldb = None, bot_instance: list or tuple = (None, 0)):
		self._lock_user = threading.Lock()
		self._lock_msg = threading.Lock()
		if client is None:
			config = ConfigParser()
			config.read('config.ini')
			self.client = Client(
				session_name = 'history_index',
				api_hash = config['account']['api_hash'],
				api_id = config['account']['api_id']
			)
		else:
			self.client = client

		if conn is None:
			try:
				config
			except NameError:
				config = ConfigParser()
				config.read('config.ini')

			self.conn = mysqldb(
				config['mysql']['host'],
				config['mysql']['username'],
				config['mysql']['passwd'],
				config['mysql']['history_db'],
			)
			self._init = False
		else:
			self.conn = conn
			self._init = True

		self.init_bot(*bot_instance)

		self.client.add_handler(MessageHandler(self.handle_all_message))

	def init_bot(self, bot_instance: str or Client, owner: int):
		if bot_instance is None: return
		self.bot = bot_search_helper(self.conn, bot_instance, owner)

	def handle_all_message(self, _: Client, msg: Message):
		threading.Thread(target = self._thread, args = (msg,), daemon = True).start()

	def _thread(self, msg: Message):
		self.user_profile_track(msg)
		self.insert_msg(msg)

	@staticmethod
	def get_hash(msg: Message):
		return hashlib.sha256(','.join((str(msg.chat.id), str(msg.message_id))).encode()).hexdigest()

	def insert_msg(self, msg: Message):
		with self._lock_user:
			self._insert_msg(msg)

	def _insert_msg(self, msg: Message):
		text = msg.text if msg.text else msg.caption if msg.caption else ''
		if text == '' or text.startswith('/') and not text.startswith('//'): # May log any message in the future
			return
		#h = self.get_hash(msg)
		sqlObj = self.conn.query1("SELECT `_id` FROM `index` WHERE `chat_id` = %s AND `message_id` = %s", (msg.chat.id, msg.message_id))
		if sqlObj is not None:
			self.conn.execute("UPDATE `index` SET `text` = %s WHERE `_id` = %s", (text, sqlObj['_id']))
			return
		#msg = self.drop_useless_part(msg)
		self.conn.execute(
			"INSERT INTO `index` (`chat_id`, `message_id`, `from_user`, `forward_from`, `text`, `timestamp`) VALUES (%s, %s, %s, %s, %s, %s)",
			(
				#h,
				msg.chat.id,
				msg.message_id,
				msg.from_user.id if msg.from_user else msg.chat.id,
				msg.forward_from.id if msg.forward_from else msg.forward_from_chat.id if msg.forward_from_chat else 0,
				text,
				datetime.datetime.fromtimestamp(msg.date).strftime('%Y-%m-%d %H:%M:%S')
				#repr(json.loads(str(msg)))
			)
		)
		self.conn.commit()

	def _user_profile_track(self, msg: Message):
		if not msg.outgoing and msg.chat.type != 'private' and msg.from_user:
			self.insert_user_profile(msg.from_user)
		if msg.forward_from:
			self.insert_user_profile(msg.forward_from)
		if msg.forward_from_chat:
			self.insert_user_profile(msg.forward_from_chat)
		self.insert_user_profile(msg.chat)

	def user_profile_track(self, msg: Message):
		with self._lock_user:
			self._user_profile_track(msg)

	def insert_user_profile(self, user: User):
		try:
			u = user_profile(user)
			sqlObj = self.conn.query1("SELECT `hash` FROM `user_history` WHERE `user_id` = %s ORDER BY `_id` DESC LIMIT 1", (user.id,))
			if sqlObj is None or u.hash != sqlObj['hash']:
				self.conn.execute(*u.sql_insert)
				self.conn.commit()
			self.insert_username(user)
		except:
			traceback.print_exc()
			print(user)

	def insert_username(self, user: User or Chat):
		if user.username is None:
			return
		sqlObj = self.conn.query1("SELECT `username` FROM `username_history` WHERE `user_id` = %s ORDER BY `_id` DESC LIMIT 1", (user.id,))
		if sqlObj and sqlObj['username'] == user.username:
			return
		self.conn.execute("INSERT INTO `username_history` (`user_id`, `username`) VALUE (%s, %s)", (user.id, user.username))

	def close(self):
		if self._init:
			self.conn.close()