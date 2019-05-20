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
import datetime

class bot_search_helper(object):

	def __preinit(self):
		self.force_query = None
		self.only_user = None
		self.only_group = None
		self.include_forward = None
		self.include_bot = None
		self.is_specify_id = None
		self.is_specify_chat = None
		self.specify_id = 0
		self.page_limit = 5

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
		self.bot.add_handler(MessageHandler(self.handle_setting, Filters.private & Filters.chat(self.owner) & Filters.command('set')))
		self.bot.add_handler(MessageHandler(self.handle_close_keyboard, Filters.private & Filters.chat(self.owner) & Filters.command('close')))
		self.bot.add_handler(CallbackQueryHandler(self.handle_query_callback, Filters.user(self.owner)))

		self.initialize_setting()
		self.bot.start()


	def handle_close_keyboard(self, client: Client, msg: Message):
		if msg.reply_to_message.from_user.is_self:
			client.edit_message_reply_markup(msg.chat.id, msg.reply_to_message.message_id)
		else:
			msg.reply('Oops! Something wrong!', True)

	def handle_setting(self, client: Client, msg: Message):
		msggroup = msg.text.split()
		if len(msggroup) == 1:
			msg.reply('Settings:\n{}'.format(self.generate_settings()), parse_mode = 'html', reply_markup = self.generate_settings_keyboard())
		elif len(msggroup) == 3:
			try:
				if msggroup[1] == 'limit':
					self.set_page_limit(msggroup[2])
			except ValueError:
				msg.reply('use `/set limit <value>` to set page limit')
			self.update_setting()

	def initialize_setting(self, init: bool = True):
		sqlObj = self.conn.query1("SELECT * FROM `settings` WHERE `user_id` = %s", self.owner)
		if sqlObj is None:
			if init:
				warnings.warn(
					'bot settings not found, try create a new one',
					RuntimeWarning
				)
			self.conn.execute("INSERT INTO `settings` (`user_id`) VALUE (%s)", self.owner)
			return self.initialize_setting()
		sqlObj.pop('user_id')
		for key, value in sqlObj.items():
			self.__setattr__(key, self._getbool(value))

	def update_setting(self):
		self.conn.execute(
			"UPDATE `settings` "
			"SET `force_query` = %s, `only_user` = %s, `only_group` = %s, `include_forward` = %s,"
			" `include_bot` = %s, `is_specify_id` = %s, `is_specify_chat` = %s, `specify_id` = %s, `page_limit` = %s "
			"WHERE `user_id` = %s",
			[self._getbool_reversed(x) for x in (
				self.force_query, self.only_user, self.only_group, self.include_forward, self.include_bot,
				self.is_specify_id, self.is_specify_chat, self.specify_id, self.page_limit, self.owner
			)]
		)

	def set_page_limit(self, limit: int):
		limit = int(limit)
		if limit > 5:
			self.page_limit = 5
		elif limit < 1:
			self.page_limit = 1
		else:
			self.page_limit = limit

	def generate_settings(self):
		return (
			'<b>Current user id:</b> <code>{owner}</code>\n' 
			'\n<b>Force Query:</b> <code>{force_query}</code>\n'
			'<b>Result each page:</b> <code>{page_limit}</code>\n'
			'<b>Only user:</b> <code>{only_user}</code>\n'
			'<b>Only group:</b> <code>{only_group}</code>\n'
			'<b>Include forward:</b> <code>{include_forward}</code>\n'
			'<b>Include bot:</b> <code>{include_bot}</code>\n'
			'<b>Use specify id:</b> <code>{is_specify_id}</code>\n'
			'<b>Specify id is chat:</b> <code>{is_specify_chat}</code>\n'
			'<b>Specify id:</b> <code>{specify_id}</code>\n\n'
			'<b>Last refresh:</b> ' + time.strftime('<code>%Y-%m-%d %H:%M:%S</code>')
			).format(
				**{x: getattr(self, x, None) for x in dir(self)}
			)

	def generate_settings_keyboard(self):
		return InlineKeyboardMarkup( inline_keyboard = [
			[InlineKeyboardButton(text = 'refresh', callback_data = b'set refresh')],
			[InlineKeyboardButton(text = 'reset', callback_data = b'set reset')]
		])

	def handle_search_user_history(self, client: Client, msg: Message):
		pass

	def handle_accurate_search_user(self, client: Client, msg: Message):
		args = msg.text.split()
		if len(args) == 1:
			return msg.reply('Please use `/su <user_id>` to search database', True)

		sqlObj = self.conn.query1("SELECT * FROM `user_history` WHERE `user_id` = %s", args[1:])
		if sqlObj is None:
			return msg.reply('Sorry, We can\'t found this user.', True)
		if sqlObj['photo_id']:
			client.send_photo(msg.chat.id, sqlObj['photo_id'], self.generate_user_info(sqlObj), 'html')
		else:
			msg.reply(self.generate_user_info(sqlObj), parse_mode = 'html')

	def generate_user_info(self, user_sqlObj: dict):
		return (
			'<b>User id</b>: <code>{user_id}</code>\n'
			'<b>First name</b>: <code>{first_name}</code>\n'
			'<b>Last name</b>: <code>{user_id}</code>\n' if user_sqlObj['last_name'] else ''
			'<b>Last update</b>: <code>{last_update}</code>\n'
		).format(**user_sqlObj)

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
			msg.reply(text, parse_mode = 'html', reply_markup = self.generate_message_search_keyboard('', search_id, 0, max_count))
		else:
			msg.reply(text, True)

	def query_message_history(self, args: list, step: int = 0, timestamp: str or datetime.datetime = ''):
		'''need passing origin args to this function'''
		args = ['%{}%'.format(x) for x in args]
		sqlStr = ' AND '.join('`text` LIKE %s' for x in args)

		if isinstance(timestamp, datetime.datetime):
			timestamp = ' AND `timetsamp` < {}'.format(timestamp.strftime('%Y-%m-%d %H:%M:%S'))
		elif timestamp != '':
			timestamp = ' AND `timetsamp` < {}'.format(timestamp)

		max_count = self.conn.query1("SELECT COUNT(*) AS `count` FROM `index` WHERE {} AND {}".format(sqlStr, self.settings_to_sql_options()), args)['count']
		if max_count:
			sqlObj = self.conn.query("SELECT * FROM `index` WHERE {0} AND {1} {4} ORDER BY `timestamp` DESC LIMIT {2}, {3}".format(
					sqlStr,
					self.settings_to_sql_options(),
					step,
					self.page_limit,
					timestamp
				), args)
			return '{3}\n\nPage: {0} / {1}\nLast_query: <code>{2}</code>'.format(
				(step // self.page_limit) + 1,
				(max_count // self.page_limit) + 1,
				time.strftime('%Y-%m-%d %H:%M:%S'),
				'\n'.join(self.show_query_msg_result(x) for x in sqlObj)
			), max_count
		return 'Empty', 0

	def settings_to_sql_options(self):
		return ' 1 = 1 '

	def show_query_msg_result(self, d: dict):
		d['timestamp'] = d['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
		if len(d['text']) > 800: # prevert message too long
			d['text'] = d['text'][:880] + '...'
		d['forward_info'] = '<b>Forward From</b>: <code>{}</code>\n'.format(d['forward_from']) if d['forward_from'] else ''

		return (
			'<b>Chat id</b>: <code>{chat_id}</code>\n'
			'<b>From user</b>: <code>{from_user}</code>\n'
			'<b>Message id</b>: <code>{message_id}</code>\n'
			'<b>Timestamp</b>: <code>{timestamp}</code>\n'
			'{forward_info}'
			'<b>Text</b>:\n<pre>{text}</pre>\n'
		).format(**d)

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
		datagroup = msg.data.split()
		if datagroup[0] == 'msg':
			if datagroup[1] in ('n', 'b', 'r'):
				sqlObj = self.get_msg_search_history(datagroup[2])
				args = eval(sqlObj['args'])
				step = (int(datagroup[3]) + (self.page_limit if datagroup[1] == 'n' else -self.page_limit)) if datagroup[1] != 'r' else 0
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
		elif datagroup[0] == 'set':
			if datagroup[1] == 'reset':
				self.conn.execute("DELETE FROM `settings` WHERE `user_id` = %s", (msg.from_user.id,))
				self.initialize_setting(False)
				msg.message.edit(self.generate_settings(), 'html', reply_markup = self.generate_settings_keyboard())
				msg.answer('Settings has been reset!')
			elif datagroup[1] == 'refresh':
				msg.message.edit(self.generate_settings(), 'html', reply_markup = self.generate_settings_keyboard())
				msg.answer()

	def generate_message_search_keyboard(self, mode: str, search_id: int, current_index: int, max_index: int):
		current_index += self.page_limit if mode == 'n' else -self.page_limit if mode == 'b' else 0
		kb = [
			[
				InlineKeyboardButton(text = 'Back', callback_data = 'msg b {} {} {}'.format(search_id, current_index, max_index).encode()),
				InlineKeyboardButton(text = 'Next', callback_data = 'msg n {} {} {}'.format(search_id, current_index, max_index).encode())
			],
			[
				InlineKeyboardButton(text = 'Re-search', callback_data = 'msg r {}'.format(search_id).encode()),
			]
		]
		if current_index + self.page_limit > max_index:
			kb[0].pop(1)
		if current_index == 0:
			kb[0].pop(0)
		if len(kb[0]) == 0:
			kb.pop(0)
		return InlineKeyboardMarkup(inline_keyboard = kb)

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

	@staticmethod
	def _getbool(s):
		if isinstance(s, str):
			return s == 'Y'
		else:
			return s

	@staticmethod
	def _getbool_reversed(s):
		if isinstance(s, bool):
			return 'Y' if s else 'N'
		else:
			return s

	def stop(self):
		return self.bot.stop()