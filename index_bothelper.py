# -*- coding: utf-8 -*-
# index_bothelper.py
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
from pyrogram import Client, Message, MessageHandler, Filters, CallbackQueryHandler, CallbackQuery,\
	InlineKeyboardMarkup, InlineKeyboardButton
import pyrogram
import hashlib
import warnings
import threading
import datetime

class bot_search_helper(object):

	def __preinit(self):
		self.force_query = None
		self.only_user = None
		self.only_group = None
		self.include_forward = None
		self.include_bot = None
		self.is_specify_id = None
		self.is_specify_group = None
		self.specify_id = None

	def __init__(self, conn: mysqldb, bot_instance: Client or str, owner_id: int):
		self.__preinit()

		if isinstance(bot_instance, Client):
			self.bot = bot_instance
		else:
			if int(pyrogram.__version__.split('.')[1]) > 11:
				warnings.warn(
					'Current is not fully support 0.12.0 or above, please use pyrogram==0.11.0 instead',
					RuntimeWarning
				)
			config = ConfigParser()
			config.read('config.ini')
			self.bot = Client(
				session_name = bot_instance,
				api_hash = config['account']['api_hash'],
				api_id = config['account']['api_id']
			)

		self.conn = conn
		self.query_lock = threading.Lock()

		self.owner = owner_id

		self.bot.add_handler(MessageHandler(self.handle_search_user_history, Filters.private & Filters.chat(self.owner) & Filters.command('su')))
		self.bot.add_handler(MessageHandler(self.handle_search_message_history, Filters.private & Filters.chat(self.owner) & Filters.command('sm')))
		self.bot.add_handler(MessageHandler(self.handle_accurate_search_user, Filters.private & Filters.chat(self.owner) & Filters.command('ua')))
		self.bot.add_handler(MessageHandler(self.handle_accurate_search_user, Filters.private & Filters.chat(self.owner) & Filters.command('ua')))
		self.bot.add_handler(CallbackQueryHandler(self.handle_query_callback, Filters.user(self.owner)))

		self.initialize_setting()
		self.bot.start()

	def handle_setting(self, client: Client, msg: Message):
		msg.reply('Settings: {}'.format(self.generate_settings()))

	def initialize_setting(self):
		sqlObj = self.conn.query1("SELECT * FROM `settings` WHERE `user_id` = %s", self.owner)
		if sqlObj is None:
			warnings.warn(
				'bot settings not found, try create a new one',
				RuntimeWarning
			)
			self.conn.execute("INSERT INTO `settings` (`user_id`) VALUE (%s)", self.owner)
			return self.initialize_setting()
		sqlObj.pop('user_id')
		for key, value in sqlObj.items():
			self.__setattr__(key, self._getbool(value))

	@staticmethod
	def _getbool(s):
		if isinstance(s, str):
			return s == 'Y'
		else:
			return s

	def generate_settings(self):
		return ('<b> Current user id:</b> <code>{owner}</code>\n' + \
			'\n<b>Force Query:</b> <code>{force_query}</code>\n'+ \
			'<b>Only user:</b> <code>{only_user}</code>\n'+ \
			'<b>Only group:</b> <code>{only_group}</code>\n'+ \
			'<b>Include forward:</b> <code>{include_forward}</code>\n'+ \
			'<b>Include bot:</b> <code>{include_bot}</code>\n'+ \
			'<b>Use specify id:</b> <code>{is_specify_id}</code>\n'+ \
			'<b>Specify id is chat:</b> <code>{is_specify_group}</code>\n'+ \
			'<b>Specify id:</b> <code>{specify_id}</code>\n').format(
				**{x: getattr(self, x, None) for x in dir(self)}
			)

	def handle_search_user_history(self, client: Client, msg: Message):
		pass

	def handle_accurate_search_user(self, client: Client, msg: Message):
		pass

	def handle_search_message_history(self, client: Client, msg: Message):
		args = msg.text.split()
		if len(args) == 1:
			return msg.reply('Please use `/sm <msg_text1> [<msg_text2> <msg_text3> ...]` to search database', True)
		args = args[1:]
		args.sort()
		if self.check_duplicate_msg_history_search_request(args) and not self.force_query:
			pass
		search_id = self.insert_msg_query_history(args)
		args = ['%{}%'.format(x) for x in args]
		sqlStr = ' AND '.join('`text` LIKE %s' for x in args) if len(args) > 1 else '`text` LIKE %s'
		max_count = self.conn.query1("SELECT COUNT(*) AS `count` FROM `index` WHERE {} ORDER BY `timestamp` DESC LIMIT 0, 5".format(sqlStr), args)['count']
		sqlObj = self.conn.query("SELECT * FROM `index` WHERE {} ORDER BY `timestamp` DESC LIMIT 0, 5".format(sqlStr), args)
		if max_count:
			msg.reply('\n'.join(self.show_query_msg_result(x) for x in sqlObj), parse_mode = 'html', reply_markup = InlineKeyboardMarkup( inline_keyboard = [
				[InlineKeyboardButton(text = 'Next', callback_data = 'msg n {} 0 {}'.format(search_id, max_count).encode())],
				[InlineKeyboardButton(text = 'Research', callback_data = 'msg r {}'.format(search_id).encode())]
			]))
		else:
			msg.reply('Empty', True)

	def show_query_msg_result(self, d: dict):
		d['timestamp'] = d['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
		return ('<b>Chat id</b>: <code>{chat_id}</code>\n' + \
			'<b>From user</b>: <code>{from_user}</code>\n' + \
			'<b>Message id</b>: <code>{message_id}</code>\n' + \
			'<b>Timestamp</b>: {timestamp}'
			'<b>Text</b>:\n<pre>{text}</pre>\n').format(**d)

	def handle_query_callback(self, client: Client, msg: CallbackQuery):
		'''
		Callback data structure:
		<main command>: like `msg'
		<sub command>: like `n' means next page
							`b' means back page
		<search id>: search sql store in database
		<current index id>
		<max index id>
		'''
		msg.data = msg.data.decode()
		if msg.data.startswith('msg'):
			datagroup = msg.data.split()
			if datagroup[1] == 'n':
				pass
			elif datagroup[1] == 'b':
				pass
			elif datagroup[1] == 'r':
				pass
		msg.answer()

	def insert_msg_query_history(self, args: list):
		with self.query_lock:
			self.conn.execute("INSERT INTO `search_history` (`args`, `hash`) VALUE (%s, %s)", (repr(args), self.get_msg_query_hash(args)))
			return self.conn.query1("SELECT `_id` FROM `search_history` ORDER BY `_id` DESC LIMIT 1")['_id']

	def check_duplicate_msg_history_search_request(self, args: list):
		return self.conn.query1("SELECT * FROM `search_history` WHERE `hash` = %s", self.get_msg_query_hash(args))

	@staticmethod
	def get_msg_query_hash(args: list):
		return hashlib.sha256(repr(args).encode()).hexdigest()

	def stop(self):
		return self.bot.stop()