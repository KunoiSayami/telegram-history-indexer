# -*- coding: utf-8 -*-
# index_bothelper.py
# Copyright (C) 2019-2021 KunoiSayami
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
import ast
import asyncio
import concurrent.futures
import datetime
import hashlib
import itertools
import logging
import math
import operator
import re
import time
import traceback
import warnings
import os
from configparser import ConfigParser
from typing import (Any, Awaitable, Callable, Dict, List, NoReturn, Optional, Sequence,
                    Tuple, Union)

import aioredis
import opencc
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram import ContinuePropagation, Client, filters
from pyrogram.types import (CallbackQuery,
                            InlineKeyboardButton, InlineKeyboardMarkup, Message)

import task
from CustomType import HashableMessageRecord as hashmsg
from CustomType import HashableUser as user
from CustomType import SQLCache
from libpy3.aiomysqldb import MySqlDB

logger = logging.getLogger('index_bothelper')


class CacheWriter:
    def __init__(self, conn: MySqlDB, update_cache: Callable[[int, int], Awaitable[None]]):
        # threading.Thread.__init__(self, daemon = True)
        self.conn: MySqlDB = conn
        self.update_cache: Callable[[int, int], Awaitable[None]] = update_cache
        self.queue: asyncio.Queue = asyncio.Queue()
        self.work: bool = True

    async def run(self) -> None:
        logger.info('CacheWriter start successful')
        # self.conn.execute("TRUNCATE `query_result_cache`")
        while self.work:
            task = asyncio.create_task(self.queue.get())
            while True:
                finish, _pending = await asyncio.wait([task], timeout=.5)
                if len(finish) > 0:
                    obj = finish.pop().result()
                    try:
                        await self._process_obj(obj)
                    except:
                        traceback.print_exc()
                if not self.work:
                    task.cancel()
                    return

    def start(self) -> concurrent.futures.Future:
        return asyncio.run_coroutine_threadsafe(self.run(), asyncio.get_event_loop())

    async def _process_obj(self, cache_obj) -> None:
        logger.debug('Cache_obj => %s', repr(cache_obj))
        if cache_obj.cache is not None:
            logger.debug('Starting #%d cache', cache_obj.cache_id)
            await self.conn.execute(
                "UPDATE `query_result_cache` SET `cache` = %s, `cache_hash` = %s, `step` = %s WHERE `_id` = %s", (
                    cache_obj.cache, cache_obj.settings_hash, cache_obj.step, cache_obj.cache_id
                ))
            logger.debug('Update #%d cache', cache_obj.cache_id)
        elif cache_obj.step is not None:
            await self.update_cache(cache_obj.cache_id, cache_obj.step)

    def push(self, cacheObj: SQLCache):
        self.queue.put_nowait(cacheObj)

    def request_stop(self) -> None:
        self.work = False


class UserCache:

    def __init__(self, client: Client, conn: MySqlDB):
        # threading.Thread.__init__(self, daemon = True)
        self.conn: MySqlDB = conn
        self.client: Client = client
        self.redis_conn: aioredis.Redis = None

    # self._cache_dict = {}

    async def create_connect(self) -> None:
        self.redis_conn = await aioredis.create_redis_pool('redis://localhost')

    # def start(self) -> concurrent.futures.Future:
    #	return asyncio.run_coroutine_threadsafe(self.run(), asyncio.get_event_loop())

    # async def run(self) -> None:
    # 	logger.info('UserCache start successful')
    # 	while True:
    # 		pending_remove = []
    # 		if self._cache_dict:
    # 			ct = time.time()
    # 			for key, item in self._cache_dict.items():
    # 				if ct - item['timestamp'] > 1800:
    # 					pending_remove.append(key)
    # 		for x in pending_remove:
    # 			self._cache_dict.pop(x)
    # 		await asyncio.sleep(60)

    async def get(self, user_id: int, no_id: bool = False) -> Union[str, int]:
        return await self._get(user_id, no_id)

    async def _get(self, user_id: int, no_id: bool) -> Union[str, int]:
        query_name = f'indexcache_{user_id}'
        obj = self.redis_conn.get(query_name)
        if obj is not None:
            sql_obj = await self.conn.query1("SELECT * FROM `user_index` WHERE `user_id` = %s", user_id)
            if sql_obj is not None:
                obj = user(**sql_obj).full_name
                await self.redis_conn.set(query_name, obj, expire=600)
            # self._cache_dict.update({user_id: {'full_name': user(**sql_obj).full_name, 'timestamp': time.time()}})
            else:
                return user_id
        else:
            # self._cache_dict[user_id]['timestamp'] = time.time()
            obj = obj.decode()
            await self.redis_conn.expire(query_name, 600)
        return '{1}</code> (<code>{0}'.format(user_id, obj) if not no_id else obj

    async def close(self) -> None:
        self.redis_conn.close()
        await self.redis_conn.wait_closed()


class BotSearchHelper:
    STEP = re.compile(r'Page: (\d+) / \d+')
    PAGE_MAX = 5
    CACHE_PAGE_SIZE = 20
    CACHE_START_REFRESH = 2

    def __init__(self, conn: Optional[MySqlDB] = None, bot_instance: Union[Client, str] = '', owner_id: int = 0):
        self.force_query = None
        self.only_user = None
        self.only_group = None
        self.except_forward = None
        self.except_bot = None
        self.use_specify_user_id = None
        self.use_specify_chat_id = None
        self.specify_user_id = 0
        self.specify_chat_id = 0
        self.page_limit = 0
        self.show_info_detail = None

        self.owner = owner_id
        self.bot_id = 0
        self.cache_channel = 0

        self.bot: Client

        if isinstance(bot_instance, Client):
            self.bot = bot_instance
        else:
            config = ConfigParser()
            config.read('config.ini')
            self.bot = Client(
                'index_bot',
                config['account']['api_id'],
                config['account']['api_hash'],
                bot_token=bot_instance if bot_instance != '' else config['account']['indexbot_token'],
            )
            self.bot_id = int(
                (bot_instance if bot_instance != '' else config['account']['indexbot_token']).split(':')[0])
            self.owner = int(config['account']['owner'])
            self.cache_channel = int(config['account']['media_send_target'])

        if conn is None:
            config = ConfigParser()
            config.read('config.ini')

            self.conn = MySqlDB(
                config['mysql']['host'],
                config['mysql']['username'],
                config['mysql']['passwd'],
                config['mysql']['history_db'],
            )
            # self.conn.do_keepalive()
            self._init: bool = True
        else:
            self.conn = conn
            self._init: bool = False

        # self.redis_conn: aioredis.Redis = None

        self.db_cache_lock: asyncio.Lock = asyncio.Lock()
        self.search_lock: asyncio.Lock = asyncio.Lock()
        self.update_lock: asyncio.Lock = asyncio.Lock()
        self.edit_queue_lock: asyncio.Lock = asyncio.Lock()

        self.user_cache = UserCache(self.bot, self.conn)
        self.query_cache = CacheWriter(self.conn, self.update_cache)
        self.coroutines: List[concurrent.futures.Future] = []
        self.add_handlers()

    def add_handlers(self) -> None:
        self.bot.add_handler(
            MessageHandler(self.handle_forward, filters.private & filters.user(self.owner) & filters.forwarded), -1)

        # MessageHandler For groups
        self.bot.add_handler(MessageHandler(self.handle_join_group, filters.new_chat_members))
        self.bot.add_handler(MessageHandler(self.handle_query_edits, filters.group & filters.text))

        # MessageHandler For query
        self.bot.add_handler(
            MessageHandler(self.handle_search_user, filters.private & filters.user(self.owner) & filters.command('su')))
        self.bot.add_handler(MessageHandler(self.handle_search_message_history,
                                            filters.private & filters.user(self.owner) & filters.command('sm')))
        self.bot.add_handler(MessageHandler(self.handle_accurate_search_user,
                                            filters.private & filters.user(self.owner) & filters.command('ua')))
        self.bot.add_handler(
            MessageHandler(self.handle_setting, filters.private & filters.user(self.owner) & filters.command('set')))
        self.bot.add_handler(MessageHandler(self.handle_close_keyboard,
                                            filters.private & filters.user(self.owner) & filters.command('close')))
        self.bot.add_handler(MessageHandler(self.handle_select_message,
                                            filters.private & filters.user(self.owner) & filters.command('select')))
        self.bot.add_handler(MessageHandler(self.handle_get_document,
                                            filters.private & filters.user(self.owner) & filters.command('get')))
        self.bot.add_handler(MessageHandler(self.handle_continue_user_request, filters.private & filters.user(
            self.owner) & filters.photo & filters.command('cache')))
        self.bot.add_handler(MessageHandler(self.handle_insert_cache,
                                            filters.private & filters.user(self.owner) & filters.command('cache')))
        self.bot.add_handler(MessageHandler(self.handle_insert_newcache,
                                            filters.private & filters.user(self.owner) & filters.command('cache')))
        self.bot.add_handler(MessageHandler(self.handle_send_custom_message,
                                            filters.private & filters.user(self.owner) & filters.command('send')))
        self.bot.add_handler(MessageHandler(self.handle_send_custom_message_ex,
                                            filters.private & filters.user(self.owner) & filters.command('sendex')))
        self.bot.add_handler(MessageHandler(self.handle_get_user_online_period,
                                            filters.private & filters.user(self.owner) & filters.command(
                                                ['online', 'onlinel'])))
        self.bot.add_handler(MessageHandler(self.handle_revoke_ref,
                                            filters.private & filters.user(self.owner) & filters.command('rref')))
        self.bot.add_handler(CallbackQueryHandler(self.handle_query_callback, filters.user(self.owner)))

        # MessageHandler For media
        self.bot.add_handler(
            MessageHandler(self.handle_incoming_image, filters.media & filters.chat(self.cache_channel)))
        self.bot.add_handler(
            MessageHandler(self.handle_query_media, filters.private & filters.user(self.owner) & filters.command('qm')))
        self.bot.add_handler(MessageHandler(self.query_mapping_lists,
                                            filters.private & filters.user(self.owner) & filters.command('qc')))

    async def start(self):
        # self.bot.add_handler(DisconnectHandler(self.handle_disconnect))
        await self.user_cache.create_connect()
        if self._init:
            await self.conn.init_connection()
        # time.sleep(0.5) # Wait sometime to make sure mysql connection successful
        await self.initialize_setting()
        self.coroutines.append(self.query_cache.start())
        await self.bot.start()
        logger.info('Bot started succesful')

    async def idle(self) -> None:
        await self.bot.idle()

    async def stop(self):
        self.query_cache.request_stop()
        await self.bot.stop()
        await self.user_cache.close()
        for coroutine in self.coroutines:
            if coroutine.running():
                logger.warning('%s is still running!', coroutine)
                coroutine.cancel()
        if self._init:
            await self.conn.close()

    async def _query_current_messages(self, d: hashmsg) -> str:
        sql_obj = await self.conn.query1("SELECT * FROM `index` WHERE `chat_id` = %s AND `message_id` = %s",
                                         (d.chat_id, d.message_id))
        if sql_obj is None:
            return ''
        arg0, arg3 = await asyncio.gather(self.user_cache.get(d.from_user), self.user_cache.get(sql_obj['from_user']))
        return '<b>[ORI]</b> <code>{0}</code> (<code>{1}</code>): <pre>{2}</pre>\n<b>[EDITED]</b> <code>{3}</code> (<code>{4}</code>): <pre>{5}</pre>'.format(
            arg0, d.timestamp, d.text, arg3, sql_obj['timestamp'], sql_obj['text']
        )

    async def handle_query_edits(self, _client: Client, msg: Message) -> Optional[NoReturn]:
        if not msg.text.startswith('/edits'):
            raise ContinuePropagation
        if self.edit_queue_lock.locked():
            # if not self.edit_queue_lock.acquire(False):
            await msg.reply('Another query in progress, please wait a moment')
            return
        async with self.edit_queue_lock:
            try:
                s = time.time()
                await self._handle_query_edits(msg)
                logger.debug('Query edits time spend %.2fs', time.time() - s)
            except:
                traceback.print_exc()

    async def query_current_messages(self, edits: list) -> List[str]:
        edits = sorted(edits, key=operator.attrgetter('timestamp'), reverse=True)
        return [await self._query_current_messages(x) for x in edits]

    async def _handle_query_edits(self, msg: Message) -> None:
        edits_set = set()
        step = 0
        timediff = time.time()
        while len(edits_set) < 3:
            sql_obj = await self.conn.query(
                f"SELECT * FROM `edit_history` WHERE `chat_id` = %s ORDER BY `timestamp` DESC LIMIT {step}, {3 - len(edits_set)}",
                msg.chat.id
            )
            if sql_obj is None:
                break
            step += max(len(sql_obj) - 1, 0)
            for msgs in sql_obj:
                edits_set.add(hashmsg(**msgs))
            if len(sql_obj) < 3:
                break
        await msg.reply("%s\n\nTime spend: %.2fs" % (
            '\n\n'.join(await self.query_current_messages(list(edits_set))), time.time() - timediff
        ), parse_mode='html')

    async def handle_close_keyboard(self, _client: Client, msg: Message) -> None:
        if msg.reply_to_message.from_user.is_self:
            await msg.delete()
            await msg.reply_to_message.edit_reply_markup()
        else:
            await msg.reply('Oops! Something wrong!', True)

    async def handle_join_group(self, client: Client, msg: Message) -> None:
        if any(x.id == self.bot_id for x in msg.new_chat_members) and msg.from_user.id != self.owner:
            await client.leave_chat(msg.chat.id)
            logger.warning('Left chat %s(%d)', msg.chat.title, msg.chat.id)

    async def handle_setting(self, _client: Client, msg: Message) -> None:
        msggroup = msg.text.split()
        if len(msggroup) == 3:
            if msggroup[1] == 'limit':
                try:
                    self.set_page_limit(msggroup[2])
                except ValueError:
                    await msg.reply('use `/set limit <value>` to set page limit', True)
                    return
            elif msggroup[1] == 'id':
                try:
                    self.specify_chat_id = self.specify_user_id = int(msggroup[2])
                except ValueError:
                    await msg.reply('use `/set id <value>` to set specify id', True)
                    return
            elif msggroup[1] == 'uid':
                try:
                    self.specify_user_id = int(msggroup[2])
                except ValueError:
                    await msg.reply('use `/set uid <value>` to set specify user id', True)
                    return
            elif msggroup[1] == 'cid':
                try:
                    self.specify_chat_id = int(msggroup[2])
                except ValueError:
                    await msg.reply('use `/set cid <value>` to set specify chat id', True)
                    return
            else:
                await msg.reply('Usage: `/set (id|cid|limit) <value>`', True)
                return
            await self.update_setting()
        await msg.reply(self.generate_settings(), parse_mode='html', reply_markup=self.generate_settings_keyboard())

    async def initialize_setting(self, init: bool = True):
        sql_obj = await self.conn.query1("SELECT * FROM `settings` WHERE `user_id` = %s", self.owner)
        if sql_obj is None:
            if init:
                warnings.warn(
                    'bot settings not found, try create a new one',
                    RuntimeWarning
                )
            await self.conn.execute("INSERT INTO `settings` (`user_id`) VALUE (%s)", self.owner)
            if self.page_limit != 0:
                await self.conn.execute("UPDATE `settings` SET `page_limit` = %s", self.page_limit)
            return await self.initialize_setting()
        sql_obj.pop('user_id')
        for key, value in sql_obj.items():
            self.__setattr__(key, self._getbool(value))  # type: ignore

    async def update_setting(self) -> None:
        await self.conn.execute(
            "UPDATE `settings` "
            "SET `force_query` = %s, `only_user` = %s, `only_group` = %s, `show_info_detail` = %s, `except_forward` = %s, "
            "`except_bot` = %s, `use_specify_user_id` = %s, `use_specify_chat_id` = %s, `specify_user_id` = %s, "
            "`specify_chat_id` = %s, `page_limit` = %s "
            "WHERE `user_id` = %s",
            [self._getbool_reversed(x) for x in (  # type: ignore
                self.force_query, self.only_user, self.only_group, self.show_info_detail, self.except_forward,
                self.except_bot,
                self.use_specify_user_id, self.use_specify_chat_id, self.specify_user_id, self.specify_chat_id,
                self.page_limit,
                self.owner
            )]  # type: ignore
        )

    def set_page_limit(self, limit: int) -> None:
        limit = int(limit)
        if limit > self.PAGE_MAX:
            self.page_limit = self.PAGE_MAX
        elif limit < 1:
            self.page_limit = 1
        else:
            self.page_limit = limit

    async def handle_forward(self, client: Client, msg: Message) -> Optional[NoReturn]:
        if msg.text and msg.text.startswith('/'):
            raise ContinuePropagation
        chat_id = msg.chat.id
        msg.chat = msg.from_user = msg.entities = msg.caption_entities = None
        await client.send_message(chat_id, f'<pre>{msg}</pre>', 'html')

    def generate_settings(self) -> str:
        return (
                f'<b>Current user id:</b> <code>{self.owner}</code>\n\n'
                f'<b>Result each page:</b> <code>{self.page_limit}</code>\n'
                f'<b>Show infomation detail:</b> <code>{self.show_info_detail}</code>\n'
                f'<b>Force Query:</b> <code>{self.force_query}</code>\n'
                f'<b>Only user:</b> <code>{self.only_user}</code>\n'
                f'<b>Only group:</b> <code>{self.only_group}</code>\n'
                f'<b>Except forward:</b> <code>{self.except_forward}</code>\n'
                f'<b>Except bot:</b> <code>{self.except_bot}</code>\n\n'
                f'<b>Use specify user id:</b> <code>{self.use_specify_user_id}</code>\n'
                f'<b>Specify user id:</b> <code>{self.specify_user_id}</code>\n\n'
                f'<b>Use specify chat id:</b> <code>{self.use_specify_chat_id}</code>\n'
                f'<b>Specify chat id:</b> <code>{self.specify_chat_id}</code>\n\n'
                '<b>Last refresh:</b> ' + time.strftime('<code>%Y-%m-%d %H:%M:%S</code>')
        )

    def settings_hash(self) -> str:
        return hashlib.sha256(''.join(map(str,
                                          (
                                              self.only_user,
                                              self.only_group,
                                              self.except_forward,
                                              self.except_bot,
                                              self.use_specify_user_id,
                                              self.specify_user_id,
                                              self.use_specify_chat_id,
                                              self.specify_chat_id,
                                          )
                                          )).encode()).hexdigest()

    @staticmethod
    def generate_settings_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text='Force query', callback_data='set force toggle'),
                InlineKeyboardButton(text='User only', callback_data='set only user'),
                InlineKeyboardButton(text='Group only', callback_data='set only group')
            ],
            [
                InlineKeyboardButton(text='Specify user id', callback_data='set specify toggle'),
                InlineKeyboardButton(text='Specify chat id', callback_data='set specify chat'),
                InlineKeyboardButton(text='Reset id', callback_data='set id reset'),
            ],
            [
                InlineKeyboardButton(text='Show Detail', callback_data='set detail toggle'),
                InlineKeyboardButton(text='Reset', callback_data='set reset'),
                InlineKeyboardButton(text='Refresh', callback_data='set refresh')
            ]
        ])

    async def handle_search_user(self, _client: Client, msg: Message) -> None:
        args = msg.text.split()
        if len(args) != 2:
            await msg.reply('Please use `/su <username>` to search database', True)
            return
        args[1] = '%{}%'.format(args[1])
        sql_obj = await self.conn.query("SELECT * FROM `user_index` WHERE `first_name` LIKE %s OR `last_name` LIKE %s",
                                        (args[1], args[1]))
        if len(sql_obj) == 0:
            await msg.reply('Sorry, We can\'t found this user.', True)
            return
        await msg.reply('<b>User id</b>: <b>Full name</b>\n' + self.generate_user_list(sql_obj), parse_mode='html')

    @staticmethod
    def generate_user_list(sql_objn: Sequence[Dict]) -> str:
        return '\n'.join('<code>{user_id}</code>: <pre>{full_name}</pre>'.format(
            **user(**sql_obj).get_dict()
        ) for sql_obj in sql_objn)

    async def send_photo(self, client: Client, msg: Message, sql_obj: dict):
        _sql_obj = await self.conn.query1("SELECT `file_id` FROM `media_cache` WHERE `id` = %s", (sql_obj['photo_id'],))
        if _sql_obj:
            # TODO: test availability after 2 hours
            await client.send_photo(msg.chat.id, _sql_obj['file_id'], None, self.generate_user_info(sql_obj), 'html')
        else:
            await msg.reply(f'/MagicDownload {sql_obj["photo_id"]} {sql_obj["user_id"]}', False)
            # logger.warning('Calling deprecated get file function')
            return
            await client.download_media(sql_obj['photo_id'], 'user.jpg')
            _msg = await client.send_photo(msg.chat.id, './downloads/user.jpg', self.generate_user_info(sql_obj), 'html')
            await self.conn.execute(
                "INSERT INTO `media_cache` (`id`, `file_id`) VALUE (%s, %s)",
                (sql_obj['photo_id'], _msg.photo.file_id)
            )
            os.remove('./downloads/user.jpg')

    async def _insert_cache(self, file_id: str, bot_file_id: str) -> Optional[Dict]:
        _sql_obj = await self.conn.query1("SELECT `file_id` FROM `media_cache` WHERE `id` = %s", (file_id,))
        if _sql_obj is None:
            if bot_file_id != '':
                await self.conn.execute(
                    "INSERT INTO `media_cache` (`id`, `file_id`) VALUE (%s, %s)",
                    (file_id, bot_file_id)
                )
                print(file_id, bot_file_id)
        else:
            return _sql_obj

    async def handle_accurate_search_user(self, client: Client, msg: Message):
        if len(msg.command) != 2:
            return await msg.reply('Please use `/ua <user_id>` to search database', True)
        await self._handle_accurate_search_user(client, msg, msg.command)

    async def _handle_accurate_search_user(self, client: Client, msg: Message, args: List[str]) -> None:
        sql_obj = await self.conn.query1("SELECT * FROM `user_index` WHERE `user_id` = %s", (args[1],))
        if sql_obj is None:
            await msg.reply('Sorry, We can\'t found this user.', True)
            return
        if sql_obj['photo_id']:
            await self.send_photo(client, msg, sql_obj)
        else:
            await msg.reply(self.generate_user_info(sql_obj), parse_mode='html')

    def generate_user_info(self, user_sql_obj: Dict[str, str]) -> str:
        return (
                '<b>User id</b>: <code>{user_id}</code>\n' + \
                '<b>First name</b>: <code>{first_name}</code>\n' + \
                ('<b>Last name</b>: <code>{last_name}</code>\n' if user_sql_obj['last_name'] else '') + \
                '<b>Last update</b>: <code>{timestamp}</code>\n'
        ).format(**user_sql_obj)

    async def handle_search_message_history(self, _client: Client, msg: Message) -> None:
        args = msg.text.split()
        # if len(args) == 1:
        #	return msg.reply('Please use `/sm <msg_text1> [<msg_text2> <msg_text3> ...]` to search database', True)

        args = args[1:]

        if len(repr(args)) > 128:
            return msg.reply('Query option too long!')

        cct2s = opencc.OpenCC('t2s')
        args = list(set([cct2s.convert(x) for x in args]))
        args.sort()

        update_request = False

        search_check = await self.check_query_duplicate(args)
        if search_check is None:
            update_request = True
            search_check = await self.insert_query_cache_table(args)
        search_id, timestamp = search_check['_id'], search_check['timestamp']

        text, max_count = await self._query_history(search_id, args,
                                                    max_count=None if update_request else search_check['max_count'],
                                                    timestamp=timestamp)  # type: ignore
        if text != '404 Not found':
            await msg.reply(text, parse_mode='html',
                            reply_markup=self.generate_message_search_keyboard('', search_id, 0, max_count))  # type: ignore
        else:
            await msg.reply(text, reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text='Re-search', callback_data=f'msg r {search_id}')]]))

        if max_count != search_check['max_count']:
            await self.update_max_count(search_id, max_count)  # type: ignore

    async def handle_get_document(self, client: Client, msg: Message) -> None:
        if len(msg.command) == 1:
            await msg.reply('Please use `/get <file_id>` to get file which is store in telegram')
            return
        await client.send_chat_action(msg.chat.id, 'upload_photo')
        sql_obj = await self._insert_cache(msg.command[1], '')
        if sql_obj is None:
            await msg.reply(f'/MagicGet {msg.command[1]}')
        else:
            await client.send_cached_media(msg.chat.id, sql_obj['file_id'], f'`{msg.command[1]}`')

    async def handle_incoming_image(self, _client: Client, msg: Message) -> None:
        await msg.delete()
        await self._insert_cache(
            msg.caption,
            task.MsgTrackerThreadClass.get_file_id(
                msg,
                task.MsgTrackerThreadClass.get_msg_type(msg)
            )
        )

    async def handle_send_custom_message_ex(self, _client: Client, msg: Message) -> None:
        if len(msg.command) < 3:
            await msg.reply('Please use `/sendex <chat_id> <message> [args...]` to send custom message')
            return
        await msg.reply('/MagicSendEx {}'.format(' '.join(msg.command[1:])))

    async def handle_send_custom_message(self, _client: Client, msg: Message) -> None:
        if len(msg.command) < 3 and len(msg.command[3:]) % 2:
            await msg.reply(
                'Please use `/send <chat_id> <message> [args...]` to send custom message, args must pair (user_id, username)')
            return
        await msg.reply('/MagicSend {}'.format(' '.join(msg.command[1:])))

    @staticmethod
    def convert_to_timestamp(t: Dict) -> Dict:
        t['online_timestamp'] = int(t['online_timestamp'].timestamp())
        return t

    @staticmethod
    def format_timesteamp(t: int) -> str:
        return datetime.datetime.fromtimestamp(t).strftime('%m/%d %H:%M:%S')

    async def get_online_period_string(self, user_id: int, more_record: bool = False, detail: bool = False) -> str:
        sql_obj = await self.conn.query(
            "SELECT * FROM `online_records` WHERE `user_id` = %s ORDER BY `online_timestamp` DESC LIMIT {}".format(
                200 if more_record else 30
            ),
            user_id)
        if not sql_obj:
            return '404 record not found'

        sql_obj = map(self.convert_to_timestamp, sql_obj)
        lastonline = perv_lastonline = lastoffline = perv_lastoffline = 0

        # Reset last offline timestamp
        for x in sql_obj:
            if x['is_offline'] == 'Y':
                perv_lastoffline = lastoffline = x['online_timestamp']
                break

        total_online_second = 0
        strpool = []
        for x in sql_obj:
            if x['is_offline'] == 'Y':
                perv_lastoffline = lastoffline
                lastoffline = x['online_timestamp']
                strpool.append('`{}`~`{}`({}m)'.format(
                    self.format_timesteamp(lastonline), self.format_timesteamp(perv_lastoffline),
                    (perv_lastoffline - lastonline) // 60))
            else:
                perv_lastonline = lastonline
                lastonline = x['online_timestamp']

        # https://www.geeksforgeeks.org/python-truncate-a-list/
        del strpool[100:]
        strpool.append('Last refresh: `{}`'.format(datetime.datetime.now().replace(microsecond=0)))

        return '\n'.join(strpool)

    async def handle_get_user_online_period(self, _client: Client, msg: Message) -> None:
        if msg.chat.id > 0 and len(msg.command) < 2:
            await msg.reply('Please use `/online <user_id>` to get online period')
            return
        await msg.reply(await self.get_online_period_string(msg.command[1] if msg.chat.id > 0 else msg.from_user.id,
                                                            msg.command[0][-1] == 'l'),
                        parse_mode='markdown',
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text='Refresh', callback_data=' '.join(msg.command))
                        ]])
                        )

    async def handle_continue_user_request(self, client: Client, msg: Message) -> Optional[NoReturn]:
        if len(msg.command) <= 2:
            raise ContinuePropagation
        await msg.delete()
        await self._insert_cache(msg.command[1], msg.photo.file_id)
        msg.command.pop(1)
        await self._handle_accurate_search_user(client, msg, msg.command)

    async def handle_insert_cache(self, _client: Client, msg: Message) -> None:
        await msg.delete()
        file_type = task.MsgTrackerThreadClass.get_msg_type(msg)
        file_id = task.MsgTrackerThreadClass.get_file_id(msg, file_type)
        file_ref = task.MsgTrackerThreadClass.get_file_ref(msg, file_type)
        await self._insert_cache(msg.command[1], file_id)
        await asyncio.gather(msg.reply_cached_media(file_id, file_ref, caption=f'`{msg.command[1]}`'),
                             msg.reply_chat_action('cancel'))

    async def handle_insert_newcache(self, client: Client, msg: Message) -> None:
        await msg.delete()
        file_id = task.MsgTrackerThreadClass.get_file_id(msg, task.MsgTrackerThreadClass.get_msg_type(msg))

    def generate_args(self, args: Union[List[str], Tuple], type_: str) -> Tuple[List[str], str]:
        if len(args) == 0 and type_ == '':
            return [], ''
        ccs2t = opencc.OpenCC('s2t')
        if isinstance(args, tuple):
            args = list(args)
        tmp = list(tuple(set(items)) for items in map(lambda x: (f'%{x}%', f'%{ccs2t.convert(x)}%'), args))
        SqlStr = ' AND '.join(['({})'.format(' OR '.join('`text` LIKE %s' for y in x)) for x in tmp])
        if type_:
            if SqlStr != '':
                SqlStr = ' AND '.join((SqlStr, '`type` = %s'))
            else:
                SqlStr = '`type` = %s'
            tmp.append((type_,))
        return list(itertools.chain.from_iterable(tmp)), SqlStr

    def generate_options(self, sqlStr: str, timestamp: str) -> str:
        options = list({sqlStr, self.settings_to_sql_options(), timestamp})
        if '' in options:
            options.remove('')
        optionsStr = ' AND '.join(options)
        if optionsStr == '':
            optionsStr = '1 = 1'
        return optionsStr

    def generate_sql_options(self, args: List[str], timestamp: str = '', type_: str = '') -> Tuple[str, List[str], str]:
        '''need passing origin args to this function'''
        args, sqlStr = self.generate_args(args, type_)
        origin_timestamp = timestamp
        if timestamp != '':
            timestamp = f'`timestamp` < \'{timestamp}\''
        optionsStr = self.generate_options(sqlStr, origin_timestamp)
        return optionsStr, args, origin_timestamp

    async def update_cache(self, cache_index: int, step: int) -> None:
        # logger.debug('Calling `update_cache`, cache_index => %d, step => %d', cache_index, step)
        sql_obj = await self.conn.query1(
            "SELECT `args`, `timestamp`, `type`, `max_count` FROM `query_result_cache` WHERE `_id` = %s", cache_index)
        upper_limit = step + (self.CACHE_PAGE_SIZE // 2) * self.PAGE_MAX
        lower_limit = step - (self.CACHE_PAGE_SIZE // 2) * self.PAGE_MAX
        # logger.debug('Upper limit => %d, lower limit => %d', upper_limit, lower_limit)
        if upper_limit > sql_obj['max_count']:
            # Beyond max count, cache is not need
            # logger.debug('Upper limit beyond max_count')
            return
        if lower_limit < 0:
            lower_limit = 0
        optionsStr, args, origin_timestamp = self.generate_sql_options(ast.literal_eval(sql_obj['args']),
                                                                       str(sql_obj['timestamp']),
                                                                       sql_obj['type'])  # type: ignore
        # logger.debug('Start request sql')
        sql_obj = await self.conn.query(
            f"SELECT * FROM `{'document_' if sql_obj['type'] is not None else ''}index` WHERE {optionsStr} "
            f"ORDER BY `timestamp` DESC LIMIT {lower_limit}, {self.CACHE_PAGE_SIZE * self.PAGE_MAX}",
            args
        )
        # logger.debug('End request sql')
        # self.query_cache.push(SQLCache(cache_index, step = lower_limit, cache = repr(sql_obj)))
        await self.conn.execute("UPDATE `query_result_cache` SET `cache` = %s, `step` = %s WHERE `_id` = %s",
                                (repr(sql_obj), lower_limit, cache_index))  # type: ignore

    # logger.debug('End update cache')

    async def __cache_query(self, cache_index: int, step: int, optionsStr: str, args: List[str], table: str,
                            force_update: bool = False) -> Tuple[Dict]:
        sql_obj = await self.conn.query1(
            "SELECT `cache`, `step`, `cache_hash` FROM `query_result_cache` WHERE `_id` = %s", cache_index)
        # NOTE: Instruction to cache
        # Cache should be text, step must real step of cache
        # Cache hash should be setting hash
        cache, cache_step, cache_hash = sql_obj['cache'], sql_obj['step'], sql_obj['cache_hash']

        # logger.debug('Checking cache status: cache == "" => %s, cache_hash != current_hash => %s, force_update => %s', cache == '', cache_hash != self.settings_hash(), force_update)

        query_lower = (step - cache_step)
        if query_lower < 0:
            query_lower = 0

        if cache == '' or cache_hash != self.settings_hash() or force_update:
            # logger.debug('cache_hash => %s, current_hash => %s', cache_hash, self.settings_hash())
            # NOTE: only init cache require from this function
            lower_limit = step - (self.CACHE_PAGE_SIZE // 2) * self.PAGE_MAX
            if lower_limit < 0:
                lower_limit = 0
            # logger.debug('Querying from mysql database')
            sql_obj = await self.conn.query(
                f"SELECT * FROM `{table}` WHERE {optionsStr} ORDER BY `timestamp` DESC "
                f"LIMIT {lower_limit}, {self.CACHE_PAGE_SIZE * self.PAGE_MAX}",
                args)
            # logger.debug('Query done from mysql database')
            self.query_cache.push(
                SQLCache(cache_index, cache=repr(sql_obj), step=lower_limit, settings_hash=self.settings_hash()))
        # logger.debug ('Pushed to cache')
        else:
            sql_obj = eval(cache)  # type: ignore
            if step > self.CACHE_START_REFRESH * self.PAGE_MAX and \
                    abs((cache_step + (self.CACHE_PAGE_SIZE // 2) * self.PAGE_MAX) - step) > (
                    (self.CACHE_PAGE_SIZE - self.CACHE_START_REFRESH) // 2) * self.PAGE_MAX:
                self.query_cache.push(SQLCache(cache_index, step=step))
        # logger.debug('Request getting new cache %d, step div: %d', cache_index, abs((cache_step + (self.CACHE_PAGE_SIZE // 2)  * self.PAGE_MAX) - step))

        # logger.debug('cache size: %d, Step => %d, abs((cache_step + (self.CACHE_PAGE_SIZE // 2)  * self.PAGE_MAX) - step) => %d, cache_step => %d',
        #	len(sql_obj), step, abs((cache_step + (self.CACHE_PAGE_SIZE // 2) * self.PAGE_MAX) - step), cache_step)

        return sql_obj[query_lower: query_lower + self.page_limit]

    async def _query_history(
            self,
            cache_index: int,
            original_args: list,
            step: int = 0,
            timestamp: str = '',
            *,
            max_count: Optional[int] = None,
            callback: Callable[[Any], Any] = None,
            table: str = 'index',
            type_: str = ''
    ) -> Tuple[str, int]:
        '''need passing origin args to this function'''
        timediff = time.time()
        optionsStr, args, origin_timestamp = self.generate_sql_options(original_args, timestamp, type_)

        force_update = (max_count is None) or self.force_query

        if max_count is None or self.force_query:
            max_count = (await self.conn.query1(f"SELECT COUNT(*) AS `count` FROM `{table}` WHERE {optionsStr}", args))[
                'count']  # type: ignore

        sql_obj = await self.__cache_query(int(cache_index), step, optionsStr, args, table, force_update)  # type: ignore

        if len(sql_obj):
            if callback: return callback(sql_obj)
            return '{3}\n\nPage: {0} / {1}\nLast query: <code>{2}</code>\nTime spend: {4:.2f}s'.format(
                (step // self.page_limit) + 1,
                # From: https://www.geeksforgeeks.org/g-fact-35-truncate-in-python/
                math.ceil(max_count / self.page_limit),
                origin_timestamp,
                '\n'.join((await self.show_query_msg_result(x)) for x in sql_obj),
                time.time() - timediff
            ), max_count  # type: ignore
        return '404 Not found', 0

    async def query_mapping_lists(self, _: Client, msg: Message):
        count = (await self.conn.query1("SELECT COUNT(*) AS `count` FROM `pending_mapping`"))['count']
        if count:
            await msg.reply(f'Total number of media file(s): {count}', True,
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text='Force Request', callback_data='magic fc mapping')]
                            ]))
        else:
            await msg.reply('Table is empty', True)

    async def handle_query_media(self, _client: Client, msg: Message) -> None:
        if len(msg.command) > 1 and msg.command[1] not in ('document', 'photo', 'video', 'animation', 'voice'):
            await msg.reply('Please use `/qm [<type> [<keyword1> <keyword2> ...]]` to query media file')
            return

        args = msg.command[2:]
        type_ = msg.command[1] if len(msg.command) > 1 else ''

        update_request = False

        if len(repr(args)) > 128:
            await msg.reply('Query option too long!')
            return

        search_check = await self.check_query_duplicate(args, type_)
        if search_check is None:
            update_request = True
            search_check = await self.insert_query_cache_table(args, type_)
        search_id, timestamp = search_check['_id'], search_check['timestamp']

        text, max_count = await self._query_history(search_id, args, 0, timestamp,
                                                    max_count=None if update_request else search_check['max_count'],
                                                    table='document_index', type_=type_)  # type: ignore
        if text != '404 Not found':
            msg.reply(text, parse_mode='html',
                      reply_markup=self.generate_message_search_keyboard('', search_id, 0, max_count, head='doc'),
                      disable_web_page_preview=True)  # type: ignore
        else:
            msg.reply(text, True)

        if max_count != search_check['max_count']:
            self.update_max_count(search_id, max_count)  # type: ignore

    def generate_select_keyboard(self, sql_obj: dict):
        if len(sql_obj) == 0: return None
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=x['text'].strip()[:14] if x['text'] != '' else '[EMPTY MSG]',
                                     callback_data=f'select detail {x["_id"]}')
            ] for x in sql_obj
        ])

    async def handle_select_message(self, _client: Client, msg: Message) -> None:
        if msg.reply_to_message is None:
            await msg.reply('Please reply a search result message (except 404 message)', True)
            return
        if msg.reply_to_message.reply_markup is None or msg.reply_to_message.reply_markup.inline_keyboard[-1][
            0].text != 'Re-search':
            await msg.reply('Inline keyboard not found!', True)
            return
        _index = msg.reply_to_message.reply_markup.inline_keyboard[-1][0].callback_data.split()[-1]
        sql_obj = await self.get_search_history(
            msg.reply_to_message.reply_markup.inline_keyboard[-1][0].callback_data.split()[-1])
        if sql_obj is None:
            await msg.reply('404 Search index not found')
            return
        step = self.STEP.search(msg.reply_to_message.text).group(1)
        kb = await self._query_history(_index, eval(sql_obj['args']), (int(step) - 1) * self.page_limit,
                                       sql_obj['timestamp'], max_count=sql_obj['max_count'],
                                       callback=self.generate_select_keyboard)  # type: ignore
        if isinstance(kb, tuple):
            return
        await msg.reply('Please select a message:', True, reply_markup=kb)

    def settings_to_sql_options(self):
        args = []

        if self.only_user:
            args.append('`chat_id` > 0')
        elif self.only_group:
            args.append('`chat_id` < 0')

        if self.except_forward:
            args.append('`forward` = 0')

        if self.use_specify_user_id:
            args.append(f'`from_user` = {self.specify_user_id}')
        if self.use_specify_chat_id:
            args.append(f'`chat_id` = {self.specify_chat_id}')

        if len(args) == 0:
            return ''
        else:
            return f"{' AND '.join(args)}"

    async def show_query_msg_result(self, d: Dict[str, Any]) -> str:
        d = await self.msg_detail_process(d)
        d['timestamp'] = d['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
        if d['text'] and len(d['text']) > 750:  # prevert message too long
            d['text'] = d['text'][:750] + '...'
        d['forward_info'] = '<b>Forward From</b>: <code>{forward_from}</code>{detail_switch}\n'.format(**d) if d[
            'forward_from'] else ''
        d['text_info'] = '<b>Text</b>:<pre>\n{}</pre>\n'.format(d['text']) if d['text'] else ''
        d['media_info'] = '<b>File type</b>: <code>{0}</code>\n<b>File id</b>: <code>{1}</code>\n'.format(d['type'], d[
            'file_id']) if 'type' in d else ''

        return (
            '<b>Chat id</b>: <code>{chat_id}</code>{detail_switch}\n'
            '<b>From user</b>: <code>{from_user}</code>{detail_switch}\n'
            '<b>Message id</b>: <code>{message_id}</code>\n'
            '<b>Timestamp</b>: <code>{timestamp}</code>\n'
            '{forward_info}'
            '{media_info}'
            '{text_info}'
        ).format(**d)

    async def msg_detail_process(self, d: Dict[str, Any]) -> Dict[str, Any]:
        if not self.show_info_detail:
            d['detail_switch'] = ''
            return d
        chat_id, from_user, forward_from = d['chat_id'], d['from_user'], d['forward_from']

        d['chat_id'], d['from_user'], d['forward_from'] = await asyncio.gather(
            self.user_cache.get(chat_id),
            self.user_cache.get(from_user),
            self.user_cache.get(forward_from))
        d['detail_switch'] = ')'
        return d

    async def generate_detail_msg(self, sql_obj: Dict) -> str:
        logger.debug('Calling `generate_detail_msg\'')
        userObj = await self.conn.query1("SELECT * FROM `user_index` WHERE `user_id` = %s", (sql_obj['from_user'],))
        r = self.generate_user_info(userObj)  # type: ignore
        if sql_obj['chat_id'] != sql_obj['from_user']:
            chatObj = await self.conn.query1("SELECT * FROM `user_index` WHERE `user_id` = %s", (sql_obj['chat_id'],))
            r += f'\n<i>Chat</i>:\n{self.generate_user_info(chatObj)}'  # type: ignore
        return f'<b>Message Details</b>:\n<i>From User</i>:\n{r}\n\n{self.show_query_msg_result(sql_obj)}'

    async def handle_page_select(self, datagroup: Tuple[str, str, int], msg: CallbackQuery):
        if datagroup[1] in ('n', 'b', 'r'):
            # logger.debug('Receive click')
            sql_obj = await self.get_search_history(datagroup[2])

            if datagroup[0] == 'doc':
                type_ = sql_obj.pop('type')
                queryArg = dict(table='document_index', type_=type_)
                keyboardArg = dict(head='doc')
            else:
                queryArg, keyboardArg = {}, {}

            args = eval(sql_obj['args'])  # type: ignore
            if datagroup[1] == 'r':
                timestr = time.strftime('%Y-%m-%d %H:%M:%S')

                await self.conn.execute("UPDATE `query_result_cache` SET `timestamp` = %s WHERE `_id` = %s",
                                        (timestr, datagroup[2]))  # type: ignore
                sql_obj['timestamp'] = timestr  # type: ignore

            step = (int(datagroup[3]) + (self.page_limit if datagroup[1] == 'n' else -self.page_limit)) if datagroup[
                                                                                                               1] != 'r' else 0
            # logger.debug('Requesting sql')

            text, max_index = await self._query_history(datagroup[2], args, step, sql_obj['timestamp'],
                                                        max_count=None if datagroup[1] == 'r' else sql_obj['max_count'],
                                                        **queryArg)  # type: ignore

            if datagroup[1] == 'r':
                reply_markup = self.generate_message_search_keyboard(datagroup[1], datagroup[2], 0, max_index,
                                                                     **keyboardArg)
            else:
                reply_markup = self.generate_message_search_keyboard(datagroup[1], *(int(x) for x in datagroup[2:]),
                                                                     **keyboardArg)
            # logger.debug('Posting Message')

            await msg.message.edit(
                text,
                parse_mode='html',
                reply_markup=reply_markup
            )

            if datagroup[1] == 'r' or max_index != sql_obj['max_count']:
                await self.update_max_count(datagroup[2], max_index)

    async def handle_query_callback(self, client: Client, msg: CallbackQuery):
        '''
            Callback data structure:
            <main command>: like `msg'
            <sub command>: like `n' means next page
                                `b' means back page
            <search id>: search sql store in database
            <current index id>
            <max index id>
        '''
        datagroup = msg.data.split()

        if datagroup[0] in ('msg', 'doc'):
            if self.update_lock.locked():
                await msg.answer('You click too fast!')
            # if not self.update_lock.acquire(False): return
            async with self.update_lock:
                if datagroup[1] == 'r':
                    await msg.answer('Please wait...', cache_time=10)
                try:
                    t = time.time()
                    await self.handle_page_select(datagroup, msg)
                    logger.debug('Time spend: %f', time.time() - t)
                finally:
                    pass

        elif datagroup[0] == 'set':

            if datagroup[1] == 'reset':
                await self.conn.execute("DELETE FROM `settings` WHERE `user_id` = %s", (msg.from_user.id,))
                await self.initialize_setting(False)
                await self.refresh_settings(msg.message)
                return await msg.answer('Settings has been reset!')

            elif datagroup[1] == 'detail':
                self.show_info_detail = not self.show_info_detail

            elif datagroup[1] == 'only':
                if datagroup[2] == 'user':
                    self.only_user = not self.only_user
                elif datagroup[2] == 'group':
                    self.only_group = not self.only_group

            elif datagroup[1] == 'specify':
                if datagroup[2] == 'toggle':
                    self.use_specify_user_id = not self.use_specify_user_id
                elif datagroup[2] == 'chat':
                    self.use_specify_chat_id = not self.use_specify_chat_id

            elif datagroup[1] == 'force':
                self.force_query = not self.force_query

            elif datagroup[1] == 'id':
                self.use_specify_user_id = False
                self.use_specify_chat_id = False
                self.specify_user_id = 0
                self.specify_chat_id = 0

            if datagroup[1] != 'refresh':
                await self.update_setting()

            await self.refresh_settings(msg.message)

        elif datagroup[0] == 'select':
            if datagroup[1] == 'detail':
                sql_obj = await self.conn.query1("SELECT * FROM `index` WHERE `_id` = %s", datagroup[2])
                await msg.message.edit(reply_markup=await self.generate_detail_keyboard(sql_obj),
                                       text=await self.generate_detail_msg(sql_obj), parse_mode='html')  # type: ignore
            elif datagroup[1] == 'fwd':
                await msg.message.reply(f'/MagicForward {datagroup[2]} {datagroup[3]}')
            elif datagroup[1] == 'get':
                await self._handle_accurate_search_user(client, msg.message, datagroup[1:])
            elif datagroup[1] == 'require':
                await self.get_media_from_file_id(datagroup[2])


        elif datagroup[0] == 'magic':
            if datagroup[1] == 'fc':
                if datagroup[2] == 'mapping':
                    await msg.message.edit_reply_markup()
                    await msg.message.reply('/MagicForceMapping', False)


        elif datagroup[0].startswith('online'):
            await msg.message.edit(await self.get_online_period_string(datagroup[1], datagroup[0][-1] == 'l'),
                                   reply_markup=msg.message.reply_markup)

        await msg.answer()

    async def handle_revoke_ref(self, client: Client, msg: Message):
        _, file_id, file_ref = msg.text.split()
        await self.conn.execute("UPDATE `file_ref` SET `ref` = %s WHERE `file_id` = %s", (file_ref, file_id))
        await client.send_message(f'/MagicGet {file_id} {file_ref}')

    async def get_media_from_file_id(self, file_id: str) -> None:
        sql_obj = await self.conn.query1(
            "SELECT `ref` FROM `file_ref` WHERE `file_id` = %s AND `timestamp` >= DATE_SUB(NOW(), INTERVAL 115 MINUTE)",
            file_id)
        if sql_obj is None:
            sql_obj = await self.conn.query1(
                "SELECT `chat_id`, `message_id` FROM `document_index` WHERE `file_id` = %s ORDER BY `timestamp` ASC LIMIT 1",
                file_id)
            await self.bot.send_message(f'/MagicUpdateRef {sql_obj["chat_id"]} {sql_obj["message_id"]}')
        else:
            await self.bot.send_message(f'/MagicGet {file_id} {sql_obj["ref"]}')

    async def generate_detail_keyboard(self, sql_obj: Dict):
        kb = [
            [
                InlineKeyboardButton(text='Forward',
                                     callback_data=f'select fwd {sql_obj["chat_id"]} {sql_obj["message_id"]}')
            ],
            [
                InlineKeyboardButton(text='Get User Detail', callback_data=f'select get {sql_obj["from_user"]}'),
                InlineKeyboardButton(text='Get Chat Detail', callback_data=f'select get {sql_obj["chat_id"]}')
            ]
        ]
        if sql_obj['from_user'] == sql_obj['chat_id']:
            kb[-1].pop(-1)
        doc_sql_obj = await self.conn.query1("SELECT * FROM `document_index` WHERE `chat_id` = %s AND `message_id` = %s",
                                             (sql_obj["chat_id"], sql_obj["message_id"]))
        if doc_sql_obj is not None:
            kb.append(
                [InlineKeyboardButton(text='Get media file', callback_data=f'select require {doc_sql_obj["file_id"]}')])
        if sql_obj['chat_id'] < 0:
            kb.append([InlineKeyboardButton(text='Goto message',
                                            url=f'https://t.me/c/{str(sql_obj["chat_id"])[4:]}/{sql_obj["message_id"]}')])
        return InlineKeyboardMarkup(inline_keyboard=kb)

    async def refresh_settings(self, msg: Message) -> None:
        await msg.edit(self.generate_settings(), 'html', reply_markup=self.generate_settings_keyboard())

    def generate_message_search_keyboard(self, mode: str, search_id: int, current_index: int, max_index: int, *,
                                         head: str = 'msg'):
        current_index += self.page_limit if mode == 'n' else -self.page_limit if mode == 'b' else 0
        kb = [
            [
                InlineKeyboardButton(text='Back', callback_data=f'{head} b {search_id} {current_index} {max_index}'),
                InlineKeyboardButton(text='Next', callback_data=f'{head} n {search_id} {current_index} {max_index}')
            ],
            [
                InlineKeyboardButton(text='Re-search', callback_data=f'{head} r {search_id}'),
            ]
        ]
        if current_index + self.page_limit > max_index - 1:
            kb[0].pop(1)
        if current_index == 0:
            kb[0].pop(0)
        if len(kb[0]) == 0:
            kb.pop(0)
        return InlineKeyboardMarkup(inline_keyboard=kb)

    async def check_query_duplicate(self, args: List, type_: str = None) -> Dict:
        # NOTE:
        # Please check None in type_ in parameter should be ''
        # None means search table
        # Two table may merge in the feature
        # Same rule in `insert_query_cache_table' function
        return await self.conn.query1(
            "SELECT `_id`, `timestamp`, `max_count` FROM `query_result_cache` WHERE `hash` = %s",
            (self.get_msg_hash(args, type_),))  # type: ignore

    async def insert_query_cache_table(self, args: list, type_: str = None) -> Dict:
        async with self.db_cache_lock:
            await self.conn.execute(
                "INSERT INTO `query_result_cache` (`type`, `args`, `hash`, `cache_hash`, `cache`) VALUE (%s, %s, %s, %s, %s)",
                (type_, repr(args), self.get_msg_hash(args, type_), self.settings_hash(), ''))  # type: ignore
            return await self.conn.query1(
                "SELECT `_id`, `max_count`, `timestamp` FROM `query_result_cache` ORDER BY `_id` DESC LIMIT 1")  # type: ignore

    async def get_search_history(self, _id: int) -> Optional[Dict]:
        return await self.conn.query1(
            "SELECT `args`, `timestamp`, `max_count`, `cache_hash`, `type` FROM `query_result_cache` WHERE `_id` = %s",
            _id, )

    async def query_from_cache_table(self, _id: int) -> Optional[Dict]:
        return await self.conn.query1("SELECT `cache` FROM `query_result_cache` WHERE `_id` = %s AND `hash` = %s",
                                      (_id, self.settings_hash()))  # type: ignore

    async def update_max_count(self, _id: int, max_count: int) -> None:
        logger.debug('Setting `max_count` to %d', max_count)
        await self.conn.execute("UPDATE `query_result_cache` SET `max_count` = %s WHERE `_id` = %s", (max_count, _id))

    @staticmethod
    def get_msg_search_hash(args: List[str]) -> str:
        return hashlib.sha256(repr(args).encode()).hexdigest()

    @staticmethod
    def get_msg_query_hash(type_: str, args: List[str]) -> str:
        if type_ is None: type_ = ''
        return hashlib.sha256((repr(args) + type_).encode()).hexdigest()

    @staticmethod
    def get_msg_hash(args: List[str], type_: str) -> str:
        if type_ is None: type_ = ' '
        return hashlib.sha256((repr(args) + type_).encode()).hexdigest()

    @staticmethod
    def _getbool(s: Union[str, bool]) -> bool:
        if isinstance(s, str):
            return s == 'Y'
        else:
            return s

    @staticmethod
    def _getbool_reversed(s: Optional[Union[str, bool]]) -> str:
        if isinstance(s, bool):
            return 'Y' if s else 'N'
        else:
            return s  # type: ignore


async def main() -> None:
    b = BotSearchHelper()
    await b.start()
    await b.idle()
    await b.stop()


if __name__ == "__main__":
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(funcName)s - %(lineno)d - %(message)s')
    asyncio.get_event_loop().run_until_complete(main())
