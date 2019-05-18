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
import time

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

		search_check = self.check_duplicate_msg_history_search_request(args)
		search_id = self.insert_msg_query_history(args) if search_check is None else search_check['_id']

		text, max_count = self.query_message_history(args)
		if max_count:
			msg.reply(text, parse_mode = 'html', reply_markup = InlineKeyboardMarkup( inline_keyboard = [
				[InlineKeyboardButton(text = 'Next', callback_data = 'msg n {} 0 {}'.format(search_id, max_count).encode())],
				[InlineKeyboardButton(text = 'Re-search', callback_data = 'msg r {}'.format(search_id).encode())]
			]))
		else:
			msg.reply(text, True)

	def query_message_history(self, args: list, step: int = 0):
		'''need passing origin args to this function'''
		args = ['%{}%'.format(x) for x in args]
		sqlStr = ' AND '.join('`text` LIKE %s' for x in args) if len(args) > 1 else '`text` LIKE %s'
		#`chat_id`, `from_user`, `message_id`, `text`, `timestamp`
		max_count = self.conn.query1("SELECT COUNT(*) AS `count` FROM `index` WHERE {} AND {}".format(sqlStr, self.settings_to_sql_options()), args)['count']
		if max_count:
			sqlObj = self.conn.query("SELECT * FROM `index` WHERE {} AND {} ORDER BY `timestamp` DESC LIMIT {}, 5".format(sqlStr, self.settings_to_sql_options(), step), args)
			return '{3}\n\nPage: {0} / {1}\nLast_query: <code>{2}</code>'.format(
				(step // 5) + 1,
				(max_count // 5) + 1,
				time.strftime('%Y-%m-%d %H:%M:%S'),
				'\n'.join(self.show_query_msg_result(x) for x in sqlObj)
			), max_count
		return 'Empty', 0

	def settings_to_sql_options(self):
		return ' 1 = 1 '

	def show_query_msg_result(self, d: dict):
		d['timestamp'] = d['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
		return ('<b>Chat id</b>: <code>{chat_id}</code>\n' + \
			'<b>From user</b>: <code>{from_user}</code>\n' + \
			'<b>Message id</b>: <code>{message_id}</code>\n' + \
			'<b>Timestamp</b>: <code>{timestamp}</code>\n'
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
			if datagroup[1] in ('n', 'b', 'r'):
				sqlObj = self.get_msg_search_history(datagroup[2])
				args = eval(sqlObj['args'])
				step = (int(datagroup[3]) + (5 if datagroup[1] == 'n' else -5)) if datagroup[1] != 'r' else 0
				text, max_index = self.query_message_history(args, step)
				if datagroup[1] != 'r':
					reply_markup = self.generate_message_search_keyboard(datagroup[1], *(int(x) for x in datagroup[2:]))
				else:
					reply_markup = self.generate_message_search_keyboard(datagroup[1], datagroup[2], 0, max_index)
				msg.message.edit(
					text,
					parse_mode = 'html',
					reply_markup = reply_markup
				)
		msg.answer()

	@staticmethod
	def generate_message_search_keyboard(mode: str, search_id: int, current_index: int, max_index: int):
		current_index += 5 if mode == 'n' else -5 if mode == 'b' else 0
		kb = [
			[
				InlineKeyboardButton(text = 'Back', callback_data = 'msg b {} {} {}'.format(search_id, current_index, max_index).encode()),
				InlineKeyboardButton(text = 'Next', callback_data = 'msg n {} {} {}'.format(search_id, current_index, max_index).encode())
			],
			[
				InlineKeyboardButton(text = 'Re-search', callback_data = 'msg r {}'.format(search_id).encode()),
			]
		]
		if current_index + 5 > max_index:
			kb[0].pop(1)
		if current_index == 0:
			kb[0].pop(0)
		if len(kb[0]) == 0:
			kb.pop(0)
		return InlineKeyboardMarkup( inline_keyboard = kb)

	def insert_msg_query_history(self, args: list):
		with self.query_lock:
			self.conn.execute("INSERT INTO `search_history` (`args`, `hash`) VALUE (%s, %s)", (repr(args), self.get_msg_query_hash(args)))
			return self.conn.query1("SELECT `_id` FROM `search_history` ORDER BY `_id` DESC LIMIT 1")['_id']

	def check_duplicate_msg_history_search_request(self, args: list):
		return self.conn.query1("SELECT `_id` FROM `search_history` WHERE `hash` = %s", self.get_msg_query_hash(args))

	def get_msg_search_history(self, _id: int):
		return self.conn.query1("SELECT `args`, `timestamp` FROM `search_history` WHERE `_id` = %s", (_id,))

	@staticmethod
	def get_msg_query_hash(args: list):
		return hashlib.sha256(repr(args).encode()).hexdigest()

	def stop(self):
		return self.bot.stop()