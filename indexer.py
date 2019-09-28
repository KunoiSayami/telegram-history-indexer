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
import traceback
import logging
import os
from configparser import ConfigParser
import pyrogram
from pyrogram import Client, Message, MessageHandler, api, ContinuePropagation, RawUpdateHandler, Update
from libpy3.mysqldb import mysqldb
from spider import iter_user_messages
import task

class history_index_class:
	def __init__(self, client: Client = None, conn: mysqldb = None, other_client: Client or bool = None):
		self.logger = logging.getLogger(__name__)
		self.logger.setLevel(level = logging.WARNING)

		config = ConfigParser()
		config.read('config.ini')

		self.filter_chat = list(map(int, config['filters']['chat'].split(', ')))
		self.filter_user = list(map(int, config['filters']['user'].split(', ')))

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
			other_client = self.other_client,
			media_send_target = config['account']['media_send_target']
		)

		self.client.add_handler(MessageHandler(self.pre_process), 888)
		self.client.add_handler(MessageHandler(self.handle_all_message), 888)
		self.client.add_handler(RawUpdateHandler(self.handle_raw_update), 999)

		self.index_dialog = iter_user_messages(self)

		self.logger.info('History indexer initialize success')

	def check_filter(self, msg: Message):
		if msg.chat.id in self.filter_chat or \
			msg.forward_from and msg.forward_from.id in self.filter_user or \
			msg.from_user and msg.from_user.id in self.filter_user:
			return True
		return False

	def upgrade_from_pyrogram_0_15_1_or_old(self):
		need_upgrade = True
		version_info = tuple(map(int, pyrogram.__version__.split('.')))
		if version_info[0] == 0 and version_info[1] >= 16:
			sqlObjs = self.conn.query("DESC `document_index`")
			if sqlObjs and sqlObjs[-2]['Field'] == 'file_ref':
				need_upgrade = False
		else:
			need_upgrade = False
		if need_upgrade:
			self.conn.execute('''ALTER TABLE `document_index`
				ALTER `file_id` DROP DEFAULT
			''')
			self.conn.execute('''ALTER TABLE `document_index`
				CHANGE COLUMN `file_id` `file_id` VARCHAR(80) NOT NULL COLLATE 'utf8_unicode_ci' AFTER `type`,
				ADD COLUMN `file_ref` VARCHAR(64) NULL DEFAULT NULL AFTER `file_id`
			''')
			self.logger.info('Upgrade database successful')

	def handle_raw_update(self, client: Client, update: Update, *_args):
		if isinstance(update, pyrogram.api.types.UpdateDeleteChannelMessages):
			return self.trackers.push(update, True)
		if isinstance(update, pyrogram.api.types.UpdateDeleteMessages):
			return self.trackers.push(update, True)
		if isinstance(update, (pyrogram.api.types.UpdateUserName, pyrogram.api.types.UpdateUserPhoto)):
			userObj = client.get_users(update.user_id)
			return self.trackers.push_user(userObj)
		if isinstance(update, pyrogram.api.types.UpdateUserStatus) and \
			isinstance(update.status, (pyrogram.api.types.UserStatusOffline, pyrogram.api.types.UserStatusOnline)):
			return self.trackers.push(update, True)

	def pre_process(self, _: Client, msg: Message):
		if msg.text and msg.from_user and msg.from_user.id == self.bot_id and msg.text.startswith('/Magic'):
			self.process_magic_function(msg)
		if msg.chat.id == self.owner: return
		raise ContinuePropagation

	def handle_all_message(self, _: Client, msg: Message):
		self.trackers.push(msg)

	def start(self):
		self.logger.info('start indexer')
		self.upgrade_from_pyrogram_0_15_1_or_old()
		self.trackers.start()
		if self.other_client != self.client:
			self.logger.debug('Starting other client')
			self.other_client.start()
		self.logger.debug('Starting main watcher')
		self.client.start()
		self.logger.debug('telegram client: logined.')
		self.index_dialog.recheck()
		self.index_dialog.start()

	def process_magic_function(self, msg: Message):
		self.client.send(api.functions.messages.ReadHistory(peer = self.client.resolve_peer(msg.chat.id), max_id = msg.message_id))
		msg.delete()
		try:
			args = msg.text.split()
			if msg.text.startswith('/MagicForward'):
				self.client.forward_messages('self', int(args[1]), int(args[2]), True)
			elif msg.text.startswith('/MagicGet'):
				self.client.send_cached_media(msg.chat.id, args[1], f'/cache `{args[1]}`')
			elif msg.text.startswith('/MagicForceMapping'):
				if self.trackers.media_thread:
					self.trackers.media_thread.force_start = True
			elif msg.text.startswith('/MagicDownload'):
				self.client.download_media(args[1], 'avatar.jpg')
				msg.reply_photo('downloads/avatar.jpg', False, f'/cache {" ".join(args[1:])}')
				os.remove('./downloads/avatar.jpg')
		except pyrogram.errors.RPCError:
			self.client.send_message('self', f'<pre>{traceback.format_exc()}</pre>', 'html')

	def close(self):
		if self._init:
			self.conn.close()

	def idle(self):
		return self.client.idle()

if __name__ == "__main__":
	history_index_class(other_client = True).start()
