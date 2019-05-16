# -*- coding: utf-8 -*-
# main.py
# Copyright (C) 2018-2019 KunoiSayami
#
# This module is part of telegram-history-indexer and is released under
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
from pyrogram import Client, Message, User, MessageHandler, Chat
import hashlib
import traceback

class user_profile(object):
	def __init__(self, user: User or Chat):
		self.user_id = user.id
		self.username = user.username if user.username else None
		self.photo_id = user.photo.big_file_id if user.photo else None

		if isinstance(user, User):
			self.first_name = user.first_name
			self.last_name = user.last_name if user.last_name else None
			self.full_name = '{} {}'.format(self.first_name, self.last_name) if self.last_name else self.first_name
		else:
			self.full_name = user.title

		self.hash = hashlib.sha256(','.join((
			str(self.user_id),
			self.username if self.username else '',
			self.full_name,
			self.photo_id if self.photo_id else ''
		)).encode()).hexdigest()
		
		if isinstance(user, User):
			self.sql_insert = (
				"INSERT INTO `user_history` (`user_id`, `username`, `first_name`, `last_name`, `photo_id`, `hash`) VALUES (%s, %s, %s, %s, %s, %s)",
				(
					self.user_id,
					self.username if self.username else '',
					self.first_name,
					self.last_name if self.last_name else '',
					self.photo_id,
					self.hash
				)
			)
		else:
			self.sql_insert = (
				"INSERT INTO `user_history` (`user_id`, `username`, `first_name` , `photo_id`, `hash`) VALUES (%s, %s, %s, %s, %s)",
				(
					self.user_id,
					self.username if self.username else '',
					self.full_name,
					self.photo_id,
					self.hash
				)
			)


class history_index_class(object):
	def __init__(self, client: Client = None, conn: mysqldb = None):
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
		
		self.client.add_handler(MessageHandler(self.handle_all_message))

	def handle_all_message(self, _: Client, msg: Message):
		self.user_profile_track(msg)
		self.insert_msg(msg)

	@staticmethod
	def get_hash(msg: Message):
		return hashlib.sha256(','.join((str(msg.chat.id), str(msg.message_id))).encode()).hexdigest()

	@staticmethod
	def drop_useless_part(msg: Message):
		msg.from_user = None
		msg.forward_from = None
		msg.forward_from_chat = None
		msg.chat = None
		return msg

	def insert_msg(self, msg: Message):
		h = self.get_hash(msg)
		text = msg.text if msg.text else msg.caption if msg.caption else ''
		if text == '': # May log any message in the future
			return
		forward_user = msg.forward_from.id if msg.forward_from else msg.forward_from_chat.id if msg.forward_from_chat else 0
		sqlObj = self.conn.query1("SELECT `_id` FROM `index` WHERE `hash` = %s", (h,))
		if sqlObj is not None:
			self.conn.execute("UPDATE `index` SET `text` = %s WHERE `_id` = %s", (text, str(sqlObj['_id'])))
			return
		chat_id = msg.chat.id
		from_user = msg.from_user.id
		msg = self.drop_useless_part(msg)
		self.conn.execute(
			"INSERT INTO `index` (`hash`, `chat_id`, `message_id`, `from_user`, `forward_from`, `text`, `origin_json`) VALUES (%s, %s, %s, %s, %s, %s, %s)",
			(
				h,
				str(chat_id),
				str(msg.message_id),
				str(from_user),
				str(forward_user),
				text,
				repr(json.loads(str(msg)))
			)
		)
		self.conn.commit()

	def user_profile_track(self, msg: Message):
		if not msg.outgoing:
			self.insert_user_profile(msg.from_user)
		if msg.forward_from:
			self.insert_user_profile(msg.forward_from)
		if msg.forward_from_chat:
			self.insert_user_profile(msg.forward_from_chat)
		self.insert_user_profile(msg.chat)

	def insert_user_profile(self, user: User):
		try:
			u = user_profile(user)
			sqlObj = self.conn.query1("SELECT `hash` FROM `user_history` WHERE `user_id` = {} ORDER BY `_id` DESC LIMIT 1".format(user.id))
			if sqlObj is None or u.hash != sqlObj['hash']:
				self.conn.execute(*u.sql_insert)
		except:
			traceback.print_exc()
			print(user)
	
	def close(self):
		if self._init:
			self.conn.close()