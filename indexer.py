from libpy3.mysqldb import mysqldb
import json
from configparser import ConfigParser
from pyrogram import Client, Message, User, MessageHandler, Chat, Filters
import pyrogram
import hashlib
import warnings
import traceback
import threading
import datetime

class user_profile(object):
	def __init__(self, user: User or Chat or None):
		self.user_id = user.id
		self.username = user.username if user.username else None
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
			self.username if self.username else '',
			self.full_name,
			self.photo_id if self.photo_id else ''
		)).encode()).hexdigest()
		
		if isinstance(user, User):
			self.sql_insert = (
				"INSERT INTO `user_history` (`user_id`, `username`, `first_name`, `last_name`, `photo_id`, `hash`) VALUES (%s, %s, %s, %s, %s, %s)",
				(
					self.user_id,
					self.username,
					self.first_name,
					self.last_name,
					self.photo_id,
					self.hash
				)
			)
		else:
			self.sql_insert = (
				"INSERT INTO `user_history` (`user_id`, `username`, `first_name` , `photo_id`, `hash`) VALUES (%s, %s, %s, %s, %s)",
				(
					self.user_id,
					self.username,
					self.full_name,
					self.photo_id,
					self.hash
				)
			)

class bot_search_helper(object):
	def __init__(self, bot_instance: Client or str, owner_id: int):
		if isinstance(bot_instance, Client):
			self.bot = bot_instance
		else:
			if pyrogram.__version__.split()[1] > 11:
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
		self.owner = owner_id
		self.bot.add_handler(MessageHandler(self.handle_search_user_history, Filters.private & Filters.chat(self.owner) & Filters.command('su')))
		self.bot.add_handler(MessageHandler(self.handle_search_message_history, Filters.private & Filters.chat(self.owner) & Filters.command('sm')))
		self.bot.add_handler(MessageHandler(self.handle_accurate_search_user, Filters.private & Filters.chat(self.owner) & Filters.command('ua')))
		self.bot.start()

	def handle_search_user_history(self, client: Client, msg: Message):
		pass

	def handle_accurate_search_user(self, client: Client, msg: Message):
		pass

	def handle_search_message_history(self, client: Client, msg: Message):
		pass

	def stop(self):
		return self.bot.stop()

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
		self.bot = bot_search_helper(bot_instance, owner)

	def handle_all_message(self, _: Client, msg: Message):
		threading.Thread(target = self._thread, args = (msg,), daemon = True).start()
	
	def _thread(self, msg: Message):
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
		with self._lock_user:
			self._insert_msg(msg)

	def _insert_msg(self, msg: Message):
		text = msg.text if msg.text else msg.caption if msg.caption else ''
		if text == '' or text.startswith('/') and not text.startswith('//'): # May log any message in the future
			return
		forward_user = msg.forward_from.id if msg.forward_from else msg.forward_from_chat.id if msg.forward_from_chat else 0
		#h = self.get_hash(msg)
		sqlObj = self.conn.query1("SELECT `_id` FROM `index` WHERE `chat_id` = %s, `message_id` = %s", map(str, (msg.chat.id, msg.message_id)))
		if sqlObj is not None:
			self.conn.execute("UPDATE `index` SET `text` = %s WHERE `_id` = %s", (text, str(sqlObj['_id'])))
			return
		chat_id = msg.chat.id
		from_user = msg.from_user.id if msg.from_user else msg.chat.id
		msg = self.drop_useless_part(msg)
		self.conn.execute(
			"INSERT INTO `index` (`chat_id`, `message_id`, `from_user`, `forward_from`, `text`, `timestamp`) VALUES (%s, %s, %s, %s, %s, %s)",
			(
				#h,
				str(chat_id),
				str(msg.message_id),
				str(from_user),
				str(forward_user),
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
		except:
			traceback.print_exc()
			print(user)
	
	def close(self):
		if self._init:
			self.conn.close()