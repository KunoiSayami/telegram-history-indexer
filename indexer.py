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
from pyrogram import Client, Message, MessageHandler, api, DisconnectHandler, ContinuePropagation
import pyrogram.errors
import traceback
from spider import iter_user_messages
import logging
import task

class history_index_class(object):
	def __init__(self, client: Client = None, conn: mysqldb = None, other_client: Client or bool = None):
		self.logger = logging.getLogger(__name__)
		self.logger.setLevel(level = logging.WARNING)

		config = ConfigParser()
		config.read('config.ini')

		self.filter_chat = [x for x in map(int, config['filters']['chat'].split(', '))]
		self.filter_user = [x for x in map(int, config['filters']['user'].split(', '))]

		self.logger.debug('Filter chat %s', repr(self.filter_chat))
		self.logger.debug('Filter user %s', repr(self.filter_user))

		self.other_client = other_client

		self.owner = int(config['account']['owner'])

		if client is None:
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

		self.trackers = task.msg_tracker_thread_class(
			self.client,
			self.conn,
			self.check_filter,
			notify = task.notify_class(self.other_client, self.owner),
			other_client = self.other_client
		)
		self.trackers.start()

		self.client.add_handler(MessageHandler(self.pre_process), 999)
		self.client.add_handler(MessageHandler(self.handle_all_message), 999)
		self.client.add_handler(DisconnectHandler(self.handle_disconnect), 999)

		self.index_dialog = iter_user_messages(self)
		self.index_dialog.recheck()

		self.logger.info('History indexer init success')

	def check_filter(self, msg: Message):
		if msg.chat.id in self.filter_chat or \
			msg.forward_from and msg.forward_from.id in self.filter_user or \
			msg.from_user and msg.from_user.id in self.filter_user:
			return True
		return False

	def pre_process(self, _: Client, msg: Message):
		if msg.text and msg.from_user and msg.from_user.id == self.bot_id and msg.text.startswith('/Magic'):
			self.process_magic_function(msg)
		if self.check_filter(msg): return
		if msg.chat.id == self.owner: return
		raise ContinuePropagation

	def handle_all_message(self, _: Client, msg: Message):
		self.trackers.push(msg)

	def start(self):
		if self.other_client != self.client:
			self.other_client.start()
		self.client.start()

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

	def close(self):
		if self._init:
			self.conn.close()

	def handle_disconnect(self, _client: Client):
		if self._init:
			self.conn.close()
		self.logger.debug('Disconnecting...')

if __name__ == "__main__":
	history_index_class(other_client = True).start()
