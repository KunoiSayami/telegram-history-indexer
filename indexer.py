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
from libpy3.mysqldb import mysqldb
import json
from configparser import ConfigParser
from pyrogram import Client, Message, User, MessageHandler, Chat, Filters, api
import hashlib
import warnings
import traceback
import threading
import datetime
from index_bothelper import bot_search_helper
import time
from spider import iter_user_messages

class user_profile(object):
	def __init__(self, user: User or Chat or None):
		self.user_id = user.id
		#self.username = user.username if user.username else None
		self.photo_id = user.photo.big_file_id if user.photo else None

		if isinstance(user, Chat) and user.type != 'private':
			self.full_name = user.title
		else:
			self.first_name = user.first_name
			self.last_name = user.last_name if user.last_name else None
			self.full_name = '{} {}'.format(self.first_name, self.last_name) if self.last_name else self.first_name

		if self.full_name is None:
			warnings.warn(
				'Caughted None first name',
				RuntimeWarning
			)
			self.full_name = ''

		self.hash = hashlib.sha256(','.join((
			str(self.user_id),
			#self.username if self.username else '',
			self.full_name,
			self.photo_id if self.photo_id else ''
		)).encode()).hexdigest()

		if isinstance(user, User):
			self.sql_insert = (
				"INSERT INTO `user_history` (`user_id`, `first_name`, `last_name`, `photo_id`, `hash`) VALUE (%s, %s, %s, %s, %s)",
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
				"INSERT INTO `user_history` (`user_id`, `first_name` , `photo_id`, `hash`) VALUE (%s, %s, %s, %s)",
				(
					self.user_id,
					#self.username,
					self.full_name,
					self.photo_id,
					self.hash
				)
			)

class history_index_class(object):
	def __init__(self, client: Client = None, conn: mysqldb = None):
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

		self.bot_id = 0

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
			self.bot_id = int(config['account']['indexbot_token'].split(':')[0])
			self.conn.do_keepalive()
			self._init = True
		else:
			self.conn = conn
			self._init = False

		self.client.add_handler(MessageHandler(self.handle_all_message))

		self.index_dialog = iter_user_messages(self)


	def handle_all_message(self, _: Client, msg: Message):
		threading.Thread(target = self._thread, args = (msg,), daemon = True).start()

	def _thread(self, msg: Message):
		self.user_profile_track(msg)
		self.insert_msg(msg)

	@staticmethod
	def get_hash(msg: Message):
		return hashlib.sha256(','.join((str(msg.chat.id), str(msg.message_id))).encode()).hexdigest()

	def insert_msg(self, msg: Message):
		with self._lock_msg:
			if self._insert_msg(msg):
				self.conn.commit()

	@staticmethod
	def get_msg_type(msg: Message):
		return 'photo' if msg.photo else 'video' if msg.video else 'animation' if msg.animation else 'document' if msg.document else 'text' if msg.text else 'error'

	@staticmethod
	def get_file_id(msg: Message, _type: str):
		if _type == 'photo':
			return msg.photo.sizes[-1].file_id
		else:
			return getattr(msg, _type).file_id

	def _insert_msg(self, msg: Message):
		if msg.text and msg.from_user and msg.from_user.id == self.bot_id and msg.text.startswith('/MagicForward'):
			args = msg.text.split()
			self.client.send(api.functions.messages.ReadHistory(self.client.resolve_peer(msg.chat.id), max_id = msg.message_id))
			msg.delete()
			try:
				self.client.forward_messages('self', int(args[1]), int(args[2]), True)
			except:
				self.client.send_message('self', f'<pre>{traceback.format_exc()}</pre>', 'html')

		if (msg.from_user and msg.chat.id == msg.from_user.id and msg.from_user.is_self): return

		text = msg.text if msg.text else msg.caption if msg.caption else ''

		if text.startswith('/') and not text.startswith('//'):
			return

		msg_type = self.get_msg_type(msg)
		if msg_type == 'error':
			if text == '': return
			else:
				msg_type = 'text'

		sqlObj = self.conn.query1("SELECT `_id` FROM `{}index` WHERE `chat_id` = %s AND `message_id` = %s".format(
				'document_' if msg_type != 'text' else ''
			), (msg.chat.id, msg.message_id))
		if sqlObj is not None:
			self.conn.execute("UPDATE `{}index` SET `text` = %s WHERE `_id` = %s".format(
					'document_' if msg_type != 'text' else ''
				), (text, sqlObj['_id']))
			return

		self.conn.execute(
			"INSERT INTO `index` (`chat_id`, `message_id`, `from_user`, `forward_from`, `text`, `timestamp`) VALUE (%s, %s, %s, %s, %s, %s)",
			(
				#h,
				msg.chat.id,
				msg.message_id,
				msg.from_user.id if msg.from_user else msg.chat.id,
				msg.forward_from.id if msg.forward_from else msg.forward_from_chat.id if msg.forward_from_chat else None,
				text,
				datetime.datetime.fromtimestamp(msg.date).strftime('%Y-%m-%d %H:%M:%S')
				#repr(json.loads(str(msg)))
			)
		)
		if msg_type != 'text':
			self.conn.execute(
				"INSERT INTO `document_index` (`chat_id`, `message_id`, `from_user`, `forward_from`, `text`, `timestamp`, `type`, `file_id`) " + \
					"VALUE (%s, %s, %s, %s, %s, %s, %s, %s)",
				(
					msg.chat.id,
					msg.message_id,
					msg.from_user.id if msg.from_user else msg.chat.id,
					msg.forward_from.id if msg.forward_from else msg.forward_from_chat.id if msg.forward_from_chat else None,
					text if len(text) > 0 else None,
					datetime.datetime.fromtimestamp(msg.date).strftime('%Y-%m-%d %H:%M:%S'),
					msg_type,
					self.get_file_id(msg, msg_type)
				)
			)
		return True


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