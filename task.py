# -*- coding: utf-8 -*-
# task.py
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
from queue import Queue
import time
import datetime
import logging
import traceback
import threading
import hashlib
import pyrogram
import os
from pyrogram import Client, Message, User, Chat
from libpy3.mysqldb import mysqldb, pymysql
from type_custom import user_profile

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

class fake_notify_class:
	def send(self):
		pass

class notify_class:
	def __init__(self, client: Client, target: int, interval: int = 60):
		self.client = client
		self.target = target
		self.interval = interval
		self.last_send = time.time()
	def send(self, msg: str):
		if time.time() - self.last_send < self.interval:
			return False
		try:
			self.client.send_message(self.target, f'```{msg}```')
		except:
			traceback.print_exc()
		finally:
			self.last_send = time.time()
		return True

class profile_photo_cache_class(threading.Thread):
	def __init__(self, client: Client, conn: mysqldb, media_send_target: int):
		threading.Thread.__init__(self, daemon = True)
		self.client = client
		self.conn = conn
		self.media_send_target = media_send_target
		self.queue = Queue()
		self.r_queue = Queue()
		self.force_start = False

	def start(self):
		threading.Thread(target = self._do_get_loop, daemon = True).start()
		threading.Thread.start(self)

	def run(self):
		logger.debug('`profile_photo_cache_class\' Thread started!')
		while not self.client.is_connected: time.sleep(0.01)
		while self.client.is_connected:
			if not self.queue.empty():
				self.exc_sql()
			dt = datetime.datetime.now()
			if (self.force_start or (dt.hour == 10 and dt.minute == 0)) and \
				self.conn.query1("SELECT * FROM `pending_mapping` LIMIT 1"):
				self.force_start = False
				self.do_get_loop()
			time.sleep(1)

	def exc_sql(self):
		try:
			file_ids = []
			while not self.queue.empty():
				file_id = self.queue.get_nowait()
				if self.conn.query1("SELECT * FROM `pending_mapping` WHERE `file_id` = %s", file_id): continue
				if self.conn.query1("SELECT * FROM `media_cache` WHERE `id` = %s", file_id): continue
				file_ids.append(file_id)
			if len(file_ids):
				self.conn.execute("INSERT INTO `pending_mapping` (`file_id`) VALUES (%s)", file_ids, len(file_ids) > 1)
		except:
			logger.exception('Error while insert sql')
			#traceback.print_exc()

	def _do_get_loop(self):
		logger.debug('`_do_get_loop\' Thread started!')
		while not self.client.is_connected: time.sleep(0.01)
		while self.client.is_connected:
			while self.r_queue.empty():
				time.sleep(1)
			self._do_forward()

	def _do_forward(self):
		while not self.r_queue.empty():
			file_id = self.r_queue.get_nowait()
			try:
				self.client.download_media(file_id, 'pendingcache.jpg')
				self.client.send_photo(self.media_send_target, 'downloads/pendingcache.jpg', file_id, disable_notification=True)
			except pyrogram.errors.exceptions.bad_request_400.FileIdInvalid:
				logger.error('The file_id: %s is invalid', file_id)
			except pyrogram.errors.FloodWait as e:
				time.sleep(e.x)
			except pyrogram.errors.RPCError:
				logger.exception('Got other RPCError: ')
			finally:
				time.sleep(0.5)
			logger.debug('send successful %s', file_id)
		os.remove('./downloads/pendingcache.jpg')

	def do_get_loop(self):
		logger.debug('Calling `do_get_loop\'')
		count = self.conn.query1("SELECT COUNT(*) AS `count` FROM `pending_mapping`")['count'] - 1
		if count < 200:
			for offset in range(0, count, 10):
				sqlObj = self.conn.query("SELECT * FROM `pending_mapping` LIMIT %s, 10", offset)
				for x in sqlObj:
					self.r_queue.put_nowait(x['file_id'])
		else:
			logger.debug('Pending mapping count is more then 200 (%d), jump over it', count)
		self.conn.execute("TRUNCATE `pending_mapping`")
		self.conn.commit()

	def push(self, file_id: str):
		self.queue.put_nowait(file_id)

class media_download_thread(threading.Thread):
	def __init__(self, client: Client, conn: mysqldb):
		threading.Thread.__init__(self, daemon=True)
		self.client = client
		self.conn = conn
		self.download_queue = Queue()

	def run(self):
		logger.debug('Download thread is ready to get file.')
		while True:
			while not self.download_queue.empty():
				try:
					file_id, file_ref = self.download_queue.get()
					if self.conn.query1("SELECT `file_id` FROM `media_store` WHERE `file_id` = %s", file_id) is not None:
						continue
					try:
						self.client.download_media(file_id, file_ref, 'image.jpg')
					except pyrogram.errors.RPCError:
						logger.error('Got rpc error while downloading %s %s', file_id, file_ref)
					
					# Insert image file into database
					# NOTE: insert binary blob should add '_binary' tag
					# From: https://stackoverflow.com/a/36861041
					with open('downloads/image.jpg', 'rb') as fin:
						self.conn.execute("INSERT INTO `media_store` (`file_id`, `body`) VALUE (%s, _binary %s)", (file_id, fin.read()))
				except:
					logger.exception('Catched exception in media_download_thread')
			time.sleep(0.5)

	def push(self, file_id: str, file_ref: str):
		self.download_queue.put_nowait((file_id, file_ref))

class msg_tracker_thread_class(threading.Thread):
	def __init__(self, client: Client, conn: mysqldb, filter_func: 'callable', *, notify: notify_class = None, other_client: Client = None, media_send_target: int = 0):
		threading.Thread.__init__(self, daemon = True)

		self.msg_queue = Queue()
		self.user_queue = Queue()
		self.client = client
		self.conn = conn
		self.media_send_target = int(media_send_target)
		self.other_client = other_client
		self.filter_func = filter_func
		self.media_download_handle = media_download_thread(self.client, self.conn)
		if self.other_client is None:
			self.other_client = self.client
		if media_send_target != 0:
			self.media_thread = profile_photo_cache_class(self.client, self.conn, self.media_send_target)
		self.notify = notify
		if self.notify is None:
			self.notify = fake_notify_class()
		self.emergency_mode = False

	def start(self):
		logger.debug('Starting `msg_tracker_thread_class\'')
		threading.Thread(target = self.user_tracker, daemon = True).start()
		threading.Thread.start(self)
		self.media_thread.start()
		self.media_download_handle.start()
		logger.debug('Start `msg_tracker_thread_class\' successful')

	def run(self):
		logger.debug('`msg_tracker_thread\' started!')
		while not self.client.is_connected: time.sleep(0.5)
		while True:
			while self.msg_queue.empty():
				time.sleep(0.1)
			try:
				self.filter_msg()
				self.conn.commit()
			except:
				logger.exception('Got exception in run thread, ignore it.')

	def _filter_msg(self, msg: Message):
		if msg.new_chat_members:
			self.conn.execute("INSERT INTO `group_history` (`chat_id`, `user_id`, `message_id`, `timestamp`) VALUES (%s, %s, %s, %s)",
				[[msg.chat.id, x.id, msg.message_id, datetime.datetime.fromtimestamp(msg.date)] for x in msg.new_chat_members], True)
			return

		text = msg.text if msg.text else msg.caption if msg.caption else ''

		if text.startswith('/') and not text.startswith('//'):
			return

		_type = self.get_msg_type(msg)
		if _type == 'error':
			if text == '':
				return
			_type = 'text'

		if msg.edit_date is not None:
			sqlObj = self.conn.query1("SELECT `_id`, `text` FROM `{}index` WHERE `chat_id` = %s AND `message_id` = %s".format(
					'document_' if _type != 'text' else ''
				), (msg.chat.id, msg.message_id))
			if sqlObj is not None:
				if text == sqlObj['text']:
					return
				self.conn.execute("UPDATE `{}index` SET `text` = %s WHERE `_id` = %s".format(
						'document_' if _type != 'text' else ''
					), (text, sqlObj['_id']))
				if msg.edit_date != 0:
					self.conn.execute("INSERT INTO `edit_history` (`chat_id` , `from_user`, `message_id`, `text`, `timestamp`) VALUE (%s, %s, %s, %s, %s)",
						(
							msg.chat.id,
							msg.from_user.id if msg.from_user else msg.chat.id,
							msg.message_id,
							sqlObj['text'],
							datetime.datetime.fromtimestamp(msg.edit_date)
						)
					)
				return

		if msg.forward_sender_name:
			sqlObj = self.conn.query1("SELECT `user_id` FROM `user_history` WHERE `full_name` LIKE %s LIMIT 1", (msg.forward_sender_name,))
			forward_from_id = sqlObj['user_id'] if sqlObj else -1001228946795
		else:
			forward_from_id = msg.forward_from.id if msg.forward_from else msg.forward_from_chat.id if msg.forward_from_chat else None

		self.conn.execute(
			"INSERT INTO `index` (`chat_id`, `message_id`, `from_user`, `forward_from`, `text`, `timestamp`) VALUE (%s, %s, %s, %s, %s, %s)",
			(
				msg.chat.id,
				msg.message_id,
				msg.from_user.id if msg.from_user else msg.chat.id,
				forward_from_id,
				text,
				datetime.datetime.fromtimestamp(msg.date)
			)
		)
		if _type != 'text':
			self.conn.execute(
				"INSERT INTO `document_index` (`chat_id`, `message_id`, `from_user`, `forward_from`, `text`, `timestamp`, `type`, `file_id`, `file_ref`) "
					"VALUE (%s, %s, %s, %s, %s, %s, %s, %s, %s)", (
						msg.chat.id,
						msg.message_id,
						msg.from_user.id if msg.from_user else msg.chat.id,
						forward_from_id,
						text if len(text) > 0 else None,
						datetime.datetime.fromtimestamp(msg.date),
						_type,
						self.get_file_id(msg, _type),
						self.get_file_ref(msg, _type)
				)
			)
			if _type == 'photo' and msg.chat.id > 0 and not msg.from_user.is_bot:
				self.media_download_handle.push(self.get_file_id(msg, _type), self.get_file_ref(msg, _type))

		logger.debug('INSERT INTO `index` %d %d %s', msg.chat.id, msg.message_id, text)

	def _insert_delete_record(self, chat_id: int, msgs: list):
		sz = [[chat_id, x] for x in msgs]
		self.conn.execute("INSERT INTO `deleted_message` (`chat_id`, `message_id`) VALUES (%s, %s)" , sz, True)

	def process_updates(self, update: "pyrogram.api.types.UpdateUserStatus" or "pyrogram.api.types.UpdateDeleteMessages"):
		# Process delete message
		if isinstance(update, pyrogram.api.types.UpdateDeleteMessages):
			sqlObj = None
			for x in update.messages:
				sqlObj = self.conn.query1("SELECT `chat_id` FROM `index` WHERE `message_id` = %s", x)
				if sqlObj:
					break
			if sqlObj:
				self._insert_delete_record(sqlObj['chat_id'], update.messages)
			return True

		if isinstance(update, pyrogram.api.types.UpdateDeleteChannelMessages):
			self._insert_delete_record(-(update.channel_id + 1000000000000), update.messages)
			return True

		# Process insert online record
		if isinstance(update, pyrogram.api.types.UpdateUserStatus):
			online_timestamp = (update.status.expires - 300) if isinstance(update.status, pyrogram.api.types.UserStatusOnline) else \
				update.status.was_online
			self.conn.execute(
				"INSERT INTO `online_records` (`user_id`, `online_timestamp`, `is_offline`) VALUE (%s, %s, %s)",
				(
					update.user_id,
					datetime.datetime.fromtimestamp(online_timestamp),
					'N' if isinstance(update.status, pyrogram.api.types.UserStatusOnline) else 'Y'
				)
			)
			return True

		return False

	def filter_msg(self):
		while not self.msg_queue.empty():
			msg = self.msg_queue.get_nowait()
			if self.process_updates(msg):
				continue
			if self.filter_func(msg):
				continue
			try:
				self._filter_msg(msg)
			except:
				self.emergency_mode = True
				self.notify.send(traceback.format_exc())
				traceback.print_exc()
			else:
				self.emergency_mode = False
			if self.emergency_mode:
				self.emergency_write(msg)

	def user_tracker(self):
		logger.debug('`user_tracker\' started!')
		while not self.client.is_connected: time.sleep(0.5)
		while True:
			while self.user_queue.empty():
				time.sleep(0.1)
			self._user_tracker()
			self.conn.commit()

	def emergency_write(self, obj: Message):
		with open(f'emergency_{"msg" if isinstance(obj, Message) else "user"}.bk', 'a') as fout:
			fout.write(repr(obj) + '\n')

	def _user_tracker(self):
		while not self.user_queue.empty():
			u = self.user_queue.get_nowait()
			try:
				self._real_user_index(u)
			except:
				self.emergency_mode = True
				traceback.print_exc()
				logger.debug('User Object detail => %s', str(u))
			if self.emergency_mode:
				self.emergency_write(u)

	def insert_username(self, user: User or Chat):
		if user.username is None:
			return
		sqlObj = self.conn.query1("SELECT `username` FROM `username_history` WHERE `user_id` = %s ORDER BY `_id` DESC LIMIT 1", (user.id,))
		if sqlObj and sqlObj['username'] == user.username:
			return
		self.conn.execute("INSERT INTO `username_history` (`user_id`, `username`) VALUE (%s, %s)", (user.id, user.username))
		self.conn.commit()

	def _real_user_index(self, user: User or Chat, *, enable_request: bool = False):
		self.insert_username(user)
		sqlObj = self.conn.query1("SELECT * FROM `user_index` WHERE `user_id` = %s", user.id)
		profileObj = user_profile(user)
		try:
			peer_id = self.client.resolve_peer(profileObj.user_id).access_hash
		except (KeyError, pyrogram.errors.RPCError, AttributeError):
			peer_id = None
		if sqlObj is None:
			is_bot = isinstance(user, User) and user.is_bot
			is_group = user.id < 0
			self.conn.execute(
				"INSERT INTO `user_index` (`user_id`, `first_name`, `last_name`, `photo_id`, `hash`, `is_bot`, `is_group`, `peer_id`) VALUE (%s, %s, %s, %s, %s, %s, %s, %s)",
				(
					profileObj.user_id,
					profileObj.first_name,
					profileObj.last_name,
					profileObj.photo_id,
					profileObj.hash,
					'Y' if is_bot else 'N',
					'Y' if is_group else 'N',
					peer_id,
				)
			)
			self.conn.execute(*profileObj.sql_insert)
			if profileObj.photo_id: self.media_thread.push(profileObj.photo_id)
			return True
		if peer_id != sqlObj['peer_id']:
			self.conn.execute("UPDATE `user_index` SET `peer_id` = %s WHERE `user_id` = %s", (peer_id, profileObj.user_id))
		if profileObj.hash != sqlObj['hash']:
			self.conn.execute(
				"UPDATE `user_index` SET `first_name` = %s, `last_name` = %s, `photo_id` = %s, `hash` = %s, `peer_id` = %s, `timestamp` = CURRENT_TIMESTAMP() WHERE `user_id` = %s",
				(
					profileObj.first_name,
					profileObj.last_name,
					profileObj.photo_id,
					profileObj.hash,
					peer_id,
					profileObj.user_id,
				)
			)
			self.conn.execute(*profileObj.sql_insert)
			if profileObj.photo_id: self.media_thread.push(profileObj.photo_id)
			return True
		elif enable_request and (datetime.datetime.now() - sqlObj['last_refresh']).total_seconds() > 3600:
			if isinstance(user, User):
				u = self.client.get_users([user.id,])[0]
			else:
				u = self.client.get_chat(user.id)
			self.conn.execute('UPDATE `user_index` SET `last_refresh` = CURRENT_TIMESTAMP() WHERE `user_id` = %s', user.id)
			return self._real_user_index(u)
		return False

	def push_user(self, user: User):
		self.user_queue.put_nowait(user)

	def push(self, msg: Message, no_user: bool = False):
		self.msg_queue.put_nowait(msg)
		if no_user: return
		users = [x.raw for x in list(set(user_profile(x) for x in [msg.from_user, msg.chat, msg.forward_from, msg.forward_from_chat, msg.via_bot]))]
		users.remove(None)
		for x in users:
			self.push_user(x)

	@staticmethod
	def get_msg_type(msg: Message):
		return 'photo' if msg.photo else \
			'video' if msg.video else \
			'animation' if msg.animation else \
			'document' if msg.document else \
			'text' if msg.text else \
			'voice' if msg.voice else 'error'

	@staticmethod
	def get_file_id(msg: Message, _type: str):
		return getattr(msg, _type).file_id

	@staticmethod
	def get_file_ref(msg: Message, _type: str):
		return getattr(msg, _type).file_ref

class check_dup(threading.Thread):
	def __init__(self, conn: mysqldb, delete: bool = False):
		threading.Thread.__init__(self, daemon = True)
		self.msg = []
		self.conn = conn
		self.delete = delete

	def check(self):
		last_id = self.conn.query1("SELECT `_id` FROM `index` ORDER BY `_id` DESC LIMIT 1")['_id']
		total_count = self.conn.query1("SELECT COUNT(*) as `count` FROM `index` WHERE `_id` < %s", last_id)['count']
		self.conn.execute("TRUNCATE `dup_check`")
		logger.debug('Last id is %d, total count: %d', last_id, total_count)
		for step in range(0, total_count, 200):
			logger.debug('Current step: %d', step)
			while True:
				try:
					sqlObjx = self.conn.query(f"SELECT `_id`, `chat_id`, `message_id`, `from_user` FROM `index` WHERE `_id` < %s LIMIT {step}, 200", (last_id,))
					break
				except:
					traceback.print_exc()
					time.sleep(1)
			if len(sqlObjx) == 0: break
			for sqlObj in sqlObjx:
				_hash = self.get_hash(sqlObj)
				#print(_hash)
				try:
					self.conn.execute("INSERT INTO `dup_check` (`hash`) VALUE (%s)", (_hash,))
				except pymysql.IntegrityError:
					self.msg.append(sqlObj['_id'])
					print(_hash)
			self.conn.commit()
		with open('pending_delete', 'w') as fout:
			fout.write(repr(self.msg))

	def _delsql(self):
		with open('pending_delete') as fin:
			ls = eval(fin.read())
		for x in ls:
			self.conn.execute("DELETE FROM `index` WHERE `_id` = %s", x)
		self.conn.commit()

	def run(self):
		if self.delete:
			self._delsql()
		else:
			self.check()

	@staticmethod
	def get_hash(sqlObj: dict):
		return hashlib.sha256(' '.join(map(str, (sqlObj['chat_id'], sqlObj['message_id'], sqlObj['from_user']))).encode()).hexdigest()
