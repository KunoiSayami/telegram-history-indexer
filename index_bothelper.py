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
import os
import math
import re

class user(object):
	def __init__(self, user_id: int, first_name: str, last_name: str or None = None, photo_id: str or None = None, **kwargs):
		self.user_id = user_id
		self.first_name = first_name
		self.last_name = last_name
		self.full_name = '{} {}'.format(first_name, last_name) if last_name else first_name
		self.photo_id = photo_id
	def get_dict(self):
		return {'user_id': self.user_id, 'full_name': self.full_name}
	def __hash__(self):
		return hash(self.user_id)
	def __eq__(self, userObj):
		return self.user_id == userObj.user_id

class bot_search_helper(object):
	STEP = re.compile(r'Page: (\d+) / \d+')

	def __preinit(self):
		self.force_query = None
		self.only_user = None
		self.only_group = None
		self.except_forward = None
		self.except_bot = None
		self.is_specify_id = None
		self.is_specify_chat = None
		self.specify_id = 0
		self.page_limit = 0
		self.show_info_detail = None

	def __init__(self, conn: mysqldb = None, bot_instance: Client or str = '', owner_id: int = 0):
		self.__preinit()

		self.owner = owner_id
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
				session_name = bot_instance if bot_instance != '' else config['account']['indexbot_token'],
				api_hash = config['account']['api_hash'],
				api_id = config['account']['api_id']
			)
			self.owner = int(config['account']['owner'])

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
				autocommit = True
			)
			self.conn.do_keepalive()
			self._init = False
		else:
			self.conn = conn
			self._init = True

		self.query_lock = threading.Lock()
		self.search_lock = threading.Lock()

		self.bot.add_handler(MessageHandler(self.handle_search_user_history, Filters.private & Filters.user(self.owner) & Filters.command('su')))
		self.bot.add_handler(MessageHandler(self.handle_search_message_history, Filters.private & Filters.user(self.owner) & Filters.command('sm')))
		self.bot.add_handler(MessageHandler(self.handle_accurate_search_user, Filters.private & Filters.user(self.owner) & Filters.command('ua')))
		self.bot.add_handler(MessageHandler(self.handle_setting, Filters.private & Filters.user(self.owner) & Filters.command('set')))
		self.bot.add_handler(MessageHandler(self.handle_close_keyboard, Filters.private & Filters.user(self.owner) & Filters.command('close')))
		self.bot.add_handler(MessageHandler(self.handle_select_message, Filters.private & Filters.user(self.owner) & Filters.command('select')))
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
			if msggroup[1] == 'limit':
				try:
					self.set_page_limit(msggroup[2])
				except ValueError:
					return msg.reply('use `/set limit <value>` to set page limit', True)
			elif msggroup[1] == 'id':
				try:
					self.specify_id = int(msggroup[2])
				except ValueError:
					return msg.reply('use `/set id <value>` to set specify id', True)
			self.update_setting()
			msg.reply(self.generate_settings(), parse_mode = 'html', reply_markup = self.generate_settings_keyboard())

	def initialize_setting(self, init: bool = True):
		sqlObj = self.conn.query1("SELECT * FROM `settings` WHERE `user_id` = %s", self.owner)
		if sqlObj is None:
			if init:
				warnings.warn(
					'bot settings not found, try create a new one',
					RuntimeWarning
				)
			self.conn.execute("INSERT INTO `settings` (`user_id`) VALUE (%s)", self.owner)
			if self.page_limit != 0:
				self.conn.execute("UPDATE `settings` SET `page_limit` = %s", self.page_limit)
			return self.initialize_setting()
		sqlObj.pop('user_id')
		for key, value in sqlObj.items():
			self.__setattr__(key, self._getbool(value))

	def update_setting(self):
		self.conn.execute(
			"UPDATE `settings` "
			"SET `force_query` = %s, `only_user` = %s, `only_group` = %s, `show_info_detail` = %s, `except_forward` = %s,"
			" `except_bot` = %s, `is_specify_id` = %s, `is_specify_chat` = %s, `specify_id` = %s, `page_limit` = %s "
			"WHERE `user_id` = %s",
			[self._getbool_reversed(x) for x in (
				self.force_query, self.only_user, self.only_group, self.show_info_detail, self.except_forward, self.except_bot,
				self.is_specify_id, self.is_specify_chat, self.specify_id, self.page_limit, self.owner
			)]
		)
		self.conn.commit()

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
			'\n'
			'<b>Result each page:</b> <code>{page_limit}</code>\n'
			'<b>Show infomation detail:</b> <code>{show_info_detail}</code>\n'
			'<b>Force Query:</b> <code>{force_query}</code>\n'
			'<b>Only user:</b> <code>{only_user}</code>\n'
			'<b>Only group:</b> <code>{only_group}</code>\n'
			'<b>Except forward:</b> <code>{except_forward}</code>\n'
			'<b>Except bot:</b> <code>{except_bot}</code>\n'
			'<b>Use specify id:</b> <code>{is_specify_id}</code>\n'
			'<b>Specify id is chat:</b> <code>{is_specify_chat}</code>\n'
			'<b>Specify id:</b> <code>{specify_id}</code>\n\n'
			'<b>Last refresh:</b> ' + time.strftime('<code>%Y-%m-%d %H:%M:%S</code>')
			).format(
				**{x: getattr(self, x, None) for x in dir(self)}
			)

	def generate_settings_keyboard(self):
		return InlineKeyboardMarkup( inline_keyboard = [
			[
				InlineKeyboardButton(text = 'Force query', callback_data = b'set force toggle'),
				InlineKeyboardButton(text = 'User only', callback_data = b'set only user'),
				InlineKeyboardButton(text = 'Group only', callback_data = b'set only group')
			],
			[
				InlineKeyboardButton(text = 'Use specify id', callback_data = b'set specify toggle'),
				InlineKeyboardButton(text = 'Specify chat', callback_data = b'set specify chat'),
				InlineKeyboardButton(text = 'Reset id', callback_data = b'set id reset')
			],
			[
				InlineKeyboardButton(text = 'Reset', callback_data = b'set reset'),
				InlineKeyboardButton(text = 'Refresh', callback_data = b'set refresh')
			]
		])

	def handle_search_user_history(self, client: Client, msg: Message):
		args = msg.text.split()
		if len(args) != 2:
			return msg.reply('Please use `/su <username>` to search database', True)
		args[1] = '%{}%'.format(args[1])
		sqlObj = self.conn.query("SELECT * FROM `user_history` WHERE `first_name` LIKE %s OR `last_name` LIKE %s", (args[1], args[1]))
		if len(sqlObj) == 0:
			return msg.reply('Sorry, We can\'t found this user.', True)
		msg.reply('<b>User id</b>: <b>Full name</b>\n' + self.generate_user_list(sqlObj), parse_mode = 'html')

	def generate_user_list(self, sqlObjx: tuple):
		return '\n'.join('<code>{user_id}</code>: <pre>{full_name}</pre>'.format(
			**sqlObj.get_dict()
		) for sqlObj in list(set(user(**x) for x in sqlObjx)))

	def send_photo(self, client: Client, msg: Message, sqlObj: dict):
		with self.search_lock:
			_sqlObj = self.conn.query1("SELECT `file_id` FROM `media_cache` WHERE `avatar_id` = %s", (sqlObj['photo_id'],))
			if _sqlObj:
				client.send_photo(msg.chat.id, _sqlObj['file_id'], self.generate_user_info(sqlObj), 'html')
			else:
				client.download_media(sqlObj['photo_id'], 'user.jpg')
				_msg = client.send_photo(msg.chat.id, './downloads/user.jpg', self.generate_user_info(sqlObj), 'html')
				self.conn.execute(
					"INSERT INTO `media_cache` (`avatar_id`, `file_id`) VALUE (%s, %s)",
					(sqlObj['photo_id'], _msg.photo.sizes[-1].file_id)
				)

	def handle_accurate_search_user(self, client: Client, msg: Message):
		args = msg.text.split()
		if len(args) != 2:
			return msg.reply('Please use `/ua <user_id>` to search database', True)
		self._handle_accurate_search_user(client, msg, args)

	def _handle_accurate_search_user(self, client: Client, msg: Message, args: list):
		sqlObj = self.conn.query1("SELECT * FROM `user_history` WHERE `user_id` = %s", args[1:])
		if sqlObj is None:
			return msg.reply('Sorry, We can\'t found this user.', True)
		if sqlObj['photo_id']:
			self.send_photo(client, msg, sqlObj)
		else:
			msg.reply(self.generate_user_info(sqlObj), parse_mode = 'html')

	def generate_user_info(self, user_sqlObj: dict):
		return (
			'<b>User id</b>: <code>{user_id}</code>\n' + \
			'<b>First name</b>: <code>{first_name}</code>\n' + \
			('<b>Last name</b>: <code>{last_name}</code>\n' if user_sqlObj['last_name'] else '') + \
			'<b>Last update</b>: <code>{last_update}</code>\n'
		).format(**user_sqlObj)

	def handle_search_message_history(self, client: Client, msg: Message):
		args = msg.text.split()
		if len(args) == 1:
			return msg.reply('Please use `/sm <msg_text1> [<msg_text2> <msg_text3> ...]` to search database', True)

		args = args[1:]
		args.sort()

		if len(repr(args)) > 128:
			return msg.reply('Query option too long!')

		search_check = self.check_duplicate_msg_history_search_request(args)
		if search_check is None:
			search_check = self.insert_msg_query_history(args)
		search_id, timestamp = search_check['_id'], search_check['timestamp']

		text, max_count = self.query_message_history(args, timestamp = timestamp)
		if max_count:
			msg.reply(text, parse_mode = 'html', reply_markup = self.generate_message_search_keyboard('', search_id, 0, max_count))
		else:
			msg.reply(text, True)

	def query_message_history(self, args: list, step: int = 0, timestamp: str or "datetime.datetime" = '', *, callback: "callable" = None):
		'''need passing origin args to this function'''
		args = ['%{}%'.format(x) for x in args]
		sqlStr = ' AND '.join('`text` LIKE %s' for x in args)

		if timestamp != '':
			timestamp = f' AND `timestamp` < \'{timestamp}\''

		max_count = self.conn.query1(f"SELECT COUNT(*) AS `count` FROM `index` WHERE {sqlStr} AND {self.settings_to_sql_options()} {timestamp}", args)['count']
		if max_count:
			sqlObj = self.conn.query(f"SELECT * FROM `index` WHERE {sqlStr} AND {self.settings_to_sql_options()} {timestamp} ORDER BY `timestamp` DESC LIMIT {step}, {self.page_limit}".format(
				), args)
			if callback: return callback(sqlObj)
			return '{3}\n\nPage: {0} / {1}\nLast_query: <code>{2}</code>'.format(
				(step // self.page_limit) + 1,
				# From: https://www.geeksforgeeks.org/g-fact-35-truncate-in-python/
				math.ceil(max_count / self.page_limit),
				time.strftime('%Y-%m-%d %H:%M:%S'),
				'\n'.join(self.show_query_msg_result(x) for x in sqlObj)
			), max_count
		return '404 Not found', 0

	def generate_select_keyboard(self, sqlObj: dict):
		if len(sqlObj) == 0: return None
		return InlineKeyboardMarkup( inline_keyboard = [
			[
				InlineKeyboardButton( text = x['text'].strip()[:14], callback_data = f'select detail {x["_id"]}'.encode())
			] for x in sqlObj
		])

	def handle_select_message(self, client: Client, msg: Message):
		if msg.reply_to_message is None:
			return msg.reply('Please reply a search result message (except 404 message)', True)
		if msg.reply_to_message.reply_markup.inline_keyboard[-1][0].text != 'Re-search':
			return msg.reply('Inline keyboard not found!', True)
		sqlObj = self.get_msg_search_history(msg.reply_to_message.reply_markup.inline_keyboard[-1][0].callback_data.decode().split()[-1])
		if sqlObj is None:
			return msg.reply('404 Search index not found')
		step = self.STEP.search(msg.reply_to_message.text).group(1)
		kb = self.query_message_history(eval(sqlObj['args']), (int(step) - 1) * self.page_limit, sqlObj['timestamp'], callback = self.generate_select_keyboard)
		if isinstance(kb, tuple):
			return
		msg.reply('Please select a message:', True, reply_markup = kb)

	def settings_to_sql_options(self):
		args = []

		if self.only_user:
			args.append('`chat_id` > 0')
		elif self.only_group:
			args.append('`chat_id` < 0')

		if self.except_forward:
			args.append('`forward` = 0')
		if self.is_specify_id:
			if self.is_specify_chat:
				args.append(f'`chat_id` = {self.specify_id}')
			else:
				args.append(f'`from_user` = {self.specify_id}')

		if len(args) == 0:
			return '1 = 1'
		else:
			return ' AND '.join(args)

	def show_query_msg_result(self, d: dict):
		d['timestamp'] = d['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
		if len(d['text']) > 750: # prevert message too long
			d['text'] = d['text'][:750] + '...'
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
				text, max_index = self.query_message_history(args, step, sqlObj['timestamp'])
				if datagroup[1] != 'r':
					reply_markup = self.generate_message_search_keyboard(datagroup[1], *(int(x) for x in datagroup[2:]))
				else:
					reply_markup = self.generate_message_search_keyboard(datagroup[1], datagroup[2], 0, max_index)
				msg.message.edit(
					text,
					parse_mode = 'html',
					reply_markup = reply_markup
				)

		elif datagroup[0] == 'set':

			if datagroup[1] == 'reset':
				self.conn.execute("DELETE FROM `settings` WHERE `user_id` = %s", (msg.from_user.id,))
				self.initialize_setting(False)
				self.refresh_settings(msg.message)
				return msg.answer('Settings has been reset!')

			elif datagroup[1] == 'refresh':
				pass

			elif datagroup[1] == 'only':
				if datagroup[2] == 'user':
					self.only_user = not self.only_user
				elif datagroup[2] == 'group':
					self.only_group = not self.only_group

			elif datagroup[1] == 'specify':
				if datagroup[2] == 'toggle':
					self.is_specify_id = not self.is_specify_id
				elif datagroup[2] == 'chat':
					self.is_specify_chat = not self.is_specify_chat

			elif datagroup[1] == 'force':
				self.force_query = not self.force_query
			
			elif datagroup[1] == 'id':
				self.is_specify_id = False
				self.is_specify_id = False
				self.specify_id = 0

			self.refresh_settings(msg.message)

		elif datagroup[0] == 'select':
			if datagroup[1] == 'detail':
				sqlObj = self.conn.query1("SELECT * FROM `index` WHERE `_id` = %s", datagroup[2])
				msg.message.edit(self.generate_detail_msg(sqlObj), 'html', reply_markup = self.generate_detail_keyboard(sqlObj))
			elif datagroup[1] == 'fwd':
				msg.message.reply(f'/MagicForward {datagroup[2]} {datagroup[3]}')
			elif datagroup[1] == 'get':
				self._handle_accurate_search_user(client, msg.message, datagroup[1:])

		msg.answer()

	def generate_detail_msg(self, sqlObj: dict):
		userObj = self.conn.query1("SELECT * FROM `user_history` WHERE `user_id` = %s", (sqlObj['from_user'],))
		r = self.generate_user_info(userObj)
		if sqlObj['chat_id'] != sqlObj['from_user']:
			chatObj = self.conn.query1("SELECT * FROM `user_history` WHERE `user_id` = %s", (sqlObj['chat_id'],))
			r += f'\n\nChat:\n{self.generate_user_info(chatObj)}'
		return f'Message Details:\nFrom User:\n{r}\n\n{self.show_query_msg_result(sqlObj)}'

	def generate_detail_keyboard(self, sqlObj: dict):
		return InlineKeyboardMarkup( inline_keyboard = [
			[
				InlineKeyboardButton(text = 'forward', callback_data = f'select fwd {sqlObj["chat_id"]} {sqlObj["message_id"]}'.encode())
			],
			[
				InlineKeyboardButton(text = 'Get User Detail', callback_data = f'select get {sqlObj["from_user"]}'.encode()),
				InlineKeyboardButton(text = 'Get Chat Detail', callback_data = f'select get {sqlObj["chat_id"]}'.encode())
			]
		])

	def refresh_settings(self, msg: Message):
		msg.edit(self.generate_settings(), 'html', reply_markup = self.generate_settings_keyboard())

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
		if current_index + self.page_limit > max_index - 1:
			kb[0].pop(1)
		if current_index == 0:
			kb[0].pop(0)
		if len(kb[0]) == 0:
			kb.pop(0)
		return InlineKeyboardMarkup(inline_keyboard = kb)

	def insert_msg_query_history(self, args: list):
		with self.query_lock:
			self.conn.execute("INSERT INTO `search_history` (`args`, `hash`) VALUE (%s, %s)", (repr(args), self.get_msg_query_hash(args)))
			return self.conn.query1("SELECT `_id`, `timestamp` FROM `search_history` ORDER BY `_id` DESC LIMIT 1")

	def check_duplicate_msg_history_search_request(self, args: list):
		return self.conn.query1("SELECT `_id`, `timestamp` FROM `search_history` WHERE `hash` = %s", self.get_msg_query_hash(args))

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
		self.bot.stop()
		if self._init:
			self.conn.close()

if __name__ == "__main__":
	b = bot_search_helper()
	try:
		b.bot.idle()
	finally:
		if b._init:
			b.conn.close()