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
from configparser import ConfigParser
from pyrogram import Client, Message, User, MessageHandler, Chat, api, DisconnectHandler
import pyrogram.errors
import hashlib
import traceback
import threading
import datetime
from spider import iter_user_messages
from type_user import user_profile

class history_index_class(object):
	def __init__(self, client: Client = None, conn: mysqldb = None, other_client: Client or bool = None):
		self._lock_user = threading.Lock()
		self._lock_msg = threading.Lock()
		self.other_client = other_client
		if client is None:
			config = ConfigParser()
			config.read('config.ini')
			self.client = Client(
				session_name = 'history_index',
				api_hash = config['account']['api_hash'],
				api_id = config['account']['api_id']
			)
			if isinstance(other_client, bool) and other_client:
				self.other_client = Client(
					session_name = 'other_session',
					api_hash = config['account']['api_hash'],
					api_id = config['account']['api_id']
				)
		else:
			self.client = client

		if self.other_client is None:
			self.other_client = self.client

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

		self.client.add_handler(MessageHandler(self.handle_all_message), 999)
		self.client.add_handler(DisconnectHandler(self.handle_disconnect), 999)

		self.index_dialog = iter_user_messages(self)
		self.index_dialog.recheck()

	def handle_all_message(self, _: Client, msg: Message):
		threading.Thread(target = self._thread, args = (msg,), daemon = True).start()

	def start(self):
		if self.other_client != self.client:
			self.other_client.start()
		self.client.start()

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

	def process_magic_function(self, msg: Message):
		self.client.send(api.functions.messages.ReadHistory(peer = self.client.resolve_peer(msg.chat.id), max_id = msg.message_id))
		msg.delete()
		try:
			args = msg.text.split()
			if msg.text.startswith('/MagicForward'):
				self.client.forward_messages('self', int(args[1]), int(args[2]), True)
			elif msg.text.startswith('/MagicGet'):
				self.client.send_cached_media(msg.chat.id, args[1], f'/cache `{args[1]}`')
		except pyrogram.errors.RPCError:
			self.client.send_message('self', f'<pre>{traceback.format_exc()}</pre>', 'html')

	def _insert_msg(self, msg: Message, force_check: bool = False):
		if msg.text and msg.from_user and msg.from_user.id == self.bot_id and msg.text.startswith('/Magic'):
			self.process_magic_function(msg)
		if (msg.from_user and msg.chat.id == msg.from_user.id and msg.from_user.is_self): return

		text = msg.text if msg.text else msg.caption if msg.caption else ''

		if text.startswith('/') and not text.startswith('//'):
			return

		msg_type = self.get_msg_type(msg)
		if msg_type == 'error':
			if text == '': return
			else:
				msg_type = 'text'

		if msg.edit_date or force_check:
			sqlObj = self.conn.query1("SELECT `_id`, `text` FROM `{}index` WHERE `chat_id` = %s AND `message_id` = %s".format(
					'document_' if msg_type != 'text' else ''
				), (msg.chat.id, msg.message_id))
			if sqlObj is not None:
				if force_check and text == sqlObj['text']: return
				self.conn.execute("UPDATE `{}index` SET `text` = %s WHERE `_id` = %s".format(
						'document_' if msg_type != 'text' else ''
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
		if msg_type != 'text':
			self.conn.execute(
				"INSERT INTO `document_index` (`chat_id`, `message_id`, `from_user`, `forward_from`, `text`, `timestamp`, `type`, `file_id`) "
					"VALUE (%s, %s, %s, %s, %s, %s, %s, %s)",
				(
					msg.chat.id,
					msg.message_id,
					msg.from_user.id if msg.from_user else msg.chat.id,
					msg.forward_from.id if msg.forward_from else msg.forward_from_chat.id if msg.forward_from_chat else None,
					text if len(text) > 0 else None,
					datetime.datetime.fromtimestamp(msg.date),
					msg_type,
					self.get_file_id(msg, msg_type)
				)
			)
		return True

	def _user_profile_track(self, msg: Message):
		users = [x.raw for x in list(set(user_profile(x) for x in [msg.from_user, msg.chat, msg.forward_from, msg.forward_from_chat, msg.via_bot]))]
		users.remove(None)
		self.real_user_index(users)

	def user_profile_track(self, msg: Message):
		with self._lock_user:
			self._user_profile_track(msg)

	def insert_username(self, user: User or Chat):
		if user.username is None:
			return
		sqlObj = self.conn.query1("SELECT `username` FROM `username_history` WHERE `user_id` = %s ORDER BY `_id` DESC LIMIT 1", (user.id,))
		if sqlObj and sqlObj['username'] == user.username:
			return
		self.conn.execute("INSERT INTO `username_history` (`user_id`, `username`) VALUE (%s, %s)", (user.id, user.username))
		self.conn.commit()

	def real_user_index(self, users: list):
		for x in users:
			self._real_user_index(x)
		self.conn.commit()

	def _real_user_index(self, user: User or Chat, disable_get: bool = False):
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

		elif not disable_get and (datetime.datetime.now() - sqlObj['last_refresh']).total_seconds() > 3600:
			if isinstance(user, User):
				u = self.client.get_users([user.id,])[0]
			else:
				u = self.client.get_chat(user.id)
			self.conn.execute('UPDATE `user_index` SET `last_refresh` = CURRENT_TIMESTAMP() WHERE `user_id` = %s', user.id)
			return self._real_user_index(u, True)

	def close(self):
		if self._init:
			self.conn.close()
	
	def handle_disconnect(self, _client: Client):
		if self._init:
			self.conn.close()

if __name__ == "__main__":
	history_index_class().start()
