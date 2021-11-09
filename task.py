# -*- coding: utf-8 -*-
# task.py
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
from __future__ import annotations
import asyncio
import concurrent.futures
import datetime
import hashlib
import logging
import time
import traceback
from abc import ABCMeta, abstractmethod
from typing import Callable

import aiofiles
import asyncpg
import pyrogram
import pyrogram.errors
from pyrogram import Client
from pyrogram.types import Chat, Message, User
from pyrogram.raw.types import UpdateDeleteChannelMessages, UpdateDeleteMessages, UpdateUserStatus, \
    UpdateUserName, UpdateUserPhoto

from custom_type import UserProfile
from libpy3.aiopgsqldb import PgSQLdb

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class SendMethod(metaclass=ABCMeta):
    @abstractmethod
    async def send(self, msg: str) -> bool:
        return NotImplemented


class FakeNotifyClass(SendMethod):
    async def send(self, _msg: str) -> bool:
        return True


class NotifyClass(SendMethod):
    def __init__(self, client: Client, target: int, interval: int = 60):
        super().__init__()
        self.client: Client = client
        self.target: int = target
        self.interval: int = interval
        self.last_send: float = time.time()

    async def send(self, msg: str) -> bool:
        if time.time() - self.last_send < self.interval:
            return False
        try:
            await self.client.send_message(self.target, f'"{msg}"', 'markdown')
        except pyrogram.errors.RPCError:
            traceback.print_exc()
        finally:
            self.last_send = time.time()
        return True


class MediaDownloader:
    def __init__(self, client: Client, conn: PgSQLdb):
        # threading.Thread.__init__(self, daemon=True)
        self.client: Client = client
        self.conn: PgSQLdb = conn
        self.download_queue: asyncio.Queue = asyncio.Queue()
        self.stop_signal: bool = False

    def push(self, file_id: str, file_ref: str = None):
        self.download_queue.put_nowait((file_id, file_ref))

    def start(self) -> concurrent.futures.Future:
        return asyncio.run_coroutine_threadsafe(self.run(), asyncio.get_event_loop())

    async def run(self) -> None:
        logger.debug('Download thread is ready to get file.')
        while not self.stop_signal:
            task = asyncio.create_task(self.download_queue.get())
            while not self.stop_signal:
                result, _pending = await asyncio.wait([task], timeout=1)
                if len(result) > 0:
                    await self.download(*result.pop().result())
                    break
                if self.stop_signal:
                    task.cancel()
                    return

    # TODO: Check function availability
    async def download(self, file_id: str, file_ref: str) -> None:
        try:
            if await self.conn.query1('''SELECT "file_id" FROM "media_store" WHERE "file_id" = $1''',
                                      file_id) is not None:
                return
            try:
                await self.client.download_media(file_id, file_ref, 'image.jpg')
            except pyrogram.errors.RPCError:
                logger.error('Got rpc error while downloading %s %s', file_id, file_ref)

            async with aiofiles.open('downloads/image.jpg', 'rb') as fin:
                # print(file_id)
                await self.conn.execute(
                    '''INSERT INTO "media_store" ("file_id", "body") VALUES ($1, $2)''',
                                        (file_id, await fin.read()))
        except:
            logger.exception('Catched exception in MediaDownloadThread')


class MsgTrackerThreadClass:
    def __init__(self, client: Client, conn: PgSQLdb, filter_func: Callable[[Message], bool], *,
                 notify: SendMethod | None = None, other_client: Client | None = None):
        # super().__init__(daemon=True)

        self.msg_queue: asyncio.Queue = asyncio.Queue()
        self.user_queue: asyncio.Queue = asyncio.Queue()
        self.client: Client = client
        self.conn: PgSQLdb = conn
        self.other_client: Client | None = other_client
        self.filter_func: Callable[[Message], bool] = filter_func
        # self.media_downloader = MediaDownloader(self.client, self.conn)
        if self.other_client is None:
            self.other_client = self.client
        self.notify = notify
        if self.notify is None:
            self.notify = FakeNotifyClass()
        self.emergency_mode: bool = False
        self.futures: list[concurrent.futures.Future] = []
        self.work: bool = True

    def start(self) -> None:
        logger.debug('Starting "MsgTrackerThreadClass\'')
        self.futures.append(asyncio.run_coroutine_threadsafe(self.user_tracker(), asyncio.get_event_loop()))
        self.futures.append(asyncio.run_coroutine_threadsafe(self.run(), asyncio.get_event_loop()))
        # self.futures.append(self.media_downloader.start())
        logger.debug('Start "MsgTrackerThreadClass\' successful')

    async def run(self) -> None:
        logger.debug('"msg_tracker_thread\' started!')
        while not self.client.is_connected:
            await asyncio.sleep(.05)
        while self.work:
            task = asyncio.create_task(self.msg_queue.get())
            while True:
                done, _pending = await asyncio.wait([task], timeout=1)
                if len(done):
                    try:
                        await self.filter_msg(done.pop().result())
                    except asyncpg.PostgresError:
                        logger.exception('Got database exception, raise it.')
                        raise
                    break
                if not self.work:
                    task.cancel()
                    return

    async def filter_msg(self, msg: Message) -> None:
        if await self.process_updates(msg):
            return
        if self.filter_func(msg):
            return
        try:
            await self._filter_msg(msg)
        except:
            self.emergency_mode = True
            await self.notify.send(traceback.format_exc())
            traceback.print_exc()
        else:
            self.emergency_mode = False
        if self.emergency_mode:
            await self.emergency_write(msg)

    async def _filter_msg(self, msg: Message) -> None:
        if msg.new_chat_members:
            # TODO: Check execute many
            await self.conn.execute(
                '''INSERT INTO "group_history" 
                ("chat_id", "user_id", "message_id", "history_date") VALUES ($1, $2, $3, $4)''',
                [(msg.chat.id, x.id, msg.message_id, datetime.datetime.fromtimestamp(msg.date)) for x in
                 msg.new_chat_members], many=True)
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
            sql_obj = await self.conn.query1(
                '''SELECT "body" FROM "{}_index" WHERE "chat_id" = $1 AND "message_id" = $2'''.format(
                    'document' if _type != 'text' else 'message'
                ), msg.chat.id, msg.message_id)
            if sql_obj is not None:
                if text == sql_obj['body']:
                    return
                await self.conn.execute(
                    '''UPDATE "{}_index" SET "body" = $1 WHERE "chat_id" = $2 AND "message_id" = $3'''.format(
                        'document' if _type != 'text' else 'message'
                    ), text, msg.chat.id, msg.message_id
                )
                if msg.edit_date != 0:
                    await self.conn.execute(
                        '''INSERT INTO "edit_history" ("chat_id" , "from_user", "message_id", "body", "message_date") 
                        VALUES ($1, $2, $3, $4, $5)''',
                        msg.chat.id,
                        msg.from_user.id if msg.from_user else msg.chat.id,
                        msg.message_id,
                        sql_obj['body'],
                        datetime.datetime.fromtimestamp(msg.edit_date)
                    )
                return

        if msg.forward_sender_name:
            sql_obj = await self.conn.query1(
                '''SELECT "user_id" FROM "user_history" WHERE "full_name" LIKE $1 LIMIT 1''',
                msg.forward_sender_name
            )
            forward_from_id = sql_obj['user_id'] if sql_obj else -1001228946795
        else:
            forward_from_id = msg.forward_from.id if msg.forward_from else \
                msg.forward_from_chat.id if msg.forward_from_chat else None

        await self.conn.execute(
            '''INSERT INTO "message_index" 
            ("chat_id", "message_id", "from_user", "forward_from", "body", "message_date")
            VALUES ($1, $2, $3, $4, $5, $6)''',
            msg.chat.id,
            msg.message_id,
            msg.from_user.id if msg.from_user else msg.chat.id,
            forward_from_id,
            text,
            datetime.datetime.fromtimestamp(msg.date)
        )
        if _type != 'text':
            file_id = self.get_file_id(msg, _type)
            #file_ref = self.get_file_ref(msg, _type)
            await self.conn.execute(
                '''INSERT INTO "document_index" 
                ("chat_id", "message_id", "from_user", "forward_from", "body", "message_date", "doc_type", "file_id") '''
                '''VALUES ($1, $2, $3, $4, $5, $6, $7, $8)''',
                msg.chat.id,
                msg.message_id,
                msg.from_user.id if msg.from_user else msg.chat.id,
                forward_from_id,
                text if len(text) > 0 else None,
                datetime.datetime.fromtimestamp(msg.date),
                _type,
                file_id
            )
            #if _type == 'photo' and msg.chat.id > 0 and not msg.from_user.is_bot:
            #    self.media_downloader.push(file_id, file_ref)
            #if await self.conn.query1('''SELECT "id" FROM "file_ref" WHERE "id" = $1''', file_id) is None:
            #    await self.conn.execute(
            #        '''INSERT INTO "file_ref" ("id", "ref") VALUES ($1, $2)''', file_id, file_ref
            #    )
            #else:
            #    await self.conn.execute(
            #        '''UPDATE "file_ref" SET "ref" = $1 WHERE "id" = $2''', file_ref, file_id
            #    )

    # logger.debug('INSERT INTO "index" %d %d %s', msg.chat.id, msg.message_id, text)

    async def _insert_delete_record(self, chat_id: int, msgs: list) -> None:
        sz = [[chat_id, x] for x in msgs]
        await self.conn.execute('''INSERT INTO "deleted_message" ("chat_id", "message_id") VALUES ($1, $2)''', sz, True)

    async def process_updates(
            self,
            update: UpdateUserStatus | UpdateDeleteMessages | UpdateDeleteChannelMessages | Message
    ) -> bool:
        # Process delete message
        if isinstance(update, pyrogram.raw.types.UpdateDeleteMessages):
            sql_obj = None
            for x in update.messages:
                sql_obj = await self.conn.query1('''SELECT "chat_id" FROM "index" WHERE "message_id" = $1''', x)
                if sql_obj:
                    break
            if sql_obj:
                await self._insert_delete_record(sql_obj['chat_id'], update.messages)
            return True

        if isinstance(update, pyrogram.raw.types.UpdateDeleteChannelMessages):
            await self._insert_delete_record(-(update.channel_id + 1000000000000), update.messages)
            return True

        # Process insert online record
        if isinstance(update, pyrogram.raw.types.UpdateUserStatus):
            entry_date = (update.status.expires - 300) if isinstance(update.status,
                                                                     pyrogram.raw.types.UserStatusOnline) else \
                update.status.was_online
            await self.conn.execute(
                '''INSERT INTO "online_record" ("user_id", "entry_date", "is_offline") VALUES ($1, $2, $3)''',
                update.user_id,
                datetime.datetime.fromtimestamp(entry_date),
                not isinstance(update.status, pyrogram.raw.types.UserStatusOnline)
            )
            return True

        return False

    async def user_tracker(self) -> None:
        logger.debug('"user_tracker\' started!')
        while not self.client.is_connected:
            await asyncio.sleep(.1)
        while True:
            while self.user_queue.empty():
                await asyncio.sleep(0.1)
            await self._user_tracker()

    # self.conn.commit()

    async def emergency_write(self, obj: Message) -> None:
        async with aiofiles.open(f'emergency_{"msg" if isinstance(obj, Message) else "user"}.bk', 'a') as fout:
            await fout.write(repr(obj) + '\n')

    async def _user_tracker(self) -> None:
        while not self.user_queue.empty():
            u = await self.user_queue.get_nowait()
            try:
                await self._real_user_index(u)
            except:
                self.emergency_mode = True
                traceback.print_exc()
                logger.debug('User Object detail => %s', str(u))
            if self.emergency_mode:
                await self.emergency_write(u)

    async def insert_username(self, user: User | Chat) -> None:
        if user.username is None:
            return
        sql_obj = await self.conn.query1(
            '''SELECT "username" FROM "username_history" WHERE "user_id" = $1 ORDER BY "_id" DESC LIMIT 1''', user.id)
        if sql_obj and sql_obj['username'] == user.username:
            return
        await self.conn.execute(
            '''INSERT INTO "username_history" ("user_id", "username") VALUES ($1, $2)''',
            user.id, user.username
        )

    # self.conn.commit()

    async def _real_user_index(self, user: User | Chat, *, enable_request: bool = False) -> bool:
        await self.insert_username(user)
        sql_obj = await self.conn.query1('''SELECT * FROM "user_index" WHERE "user_id" = $1''', user.id)
        user_profile = UserProfile(user)
        try:
            peer_id = (await self.client.resolve_peer(user_profile.user_id)).access_hash
        except (KeyError, pyrogram.errors.RPCError, AttributeError):
            peer_id = None
        if sql_obj is None:
            is_bot = isinstance(user, User) and user.is_bot
            is_group = user.id < 0
            await self.conn.execute(
                '''INSERT INTO "user_index" 
                ("user_id", "first_name", "last_name", "photo_id", "hash", "is_bot", "is_group", "peer_id") 
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)''',
                user_profile.user_id,
                user_profile.first_name,
                user_profile.last_name,
                user_profile.photo_id,
                user_profile.hash,
                is_bot,
                is_group,
                peer_id,
            )
            await self.conn.execute(user_profile.sql_statement, user_profile.sql_args)  # type: ignore
            if user_profile.photo_id:
                self.media_downloader.push(user_profile.photo_id)
            return True
        if peer_id != sql_obj['peer_id']:
            await self.conn.execute('''UPDATE "user_index" SET "peer_id" = %s WHERE "user_id" = %s''',
                                    (peer_id, user_profile.user_id))  # type: ignore
        if user_profile.hash != sql_obj['hash']:
            await self.conn.execute(
                '''UPDATE "user_index" SET 
                "first_name" = $1, "last_name" = $2, "photo_id" = $3, "hash" = $4, "peer_id" = $5, 
                "timestamp" = CURRENT_TIMESTAMP WHERE "user_id" = $6''',
                user_profile.first_name,
                user_profile.last_name,
                user_profile.photo_id,
                user_profile.hash,
                peer_id,
                user_profile.user_id,
            )
            await self.conn.execute(user_profile.sql_statement, user_profile.sql_args)  # type: ignore
            if user_profile.photo_id:
                self.media_downloader.push(user_profile.photo_id)
            return True
        elif enable_request and (datetime.datetime.now() - sql_obj['last_refresh']).total_seconds() > 3600:
            u = await self.client.get_users(user.id) if isinstance(user, User) else await self.client.get_chat(user.id)
            await self.conn.execute(
                'UPDATE "user_index" SET "last_refresh" = CURRENT_TIMESTAMP WHERE "user_id" = $1',
                user.id)
            return await self._real_user_index(u)
        return False

    def push_user(self, user: User | UpdateUserName | UpdateUserPhoto) -> None:
        self.user_queue.put_nowait(user)

    def push_no_user(self,
                     msg: Message | UpdateDeleteChannelMessages | UpdateDeleteMessages | UpdateUserStatus
                     ):
        self.msg_queue.put_nowait(msg)

    def push(self, msg: Message | pyrogram.types.Update, no_user: bool = False) -> None:
        self.msg_queue.put_nowait(msg)
        if no_user:
            return
        users = [x.raw for x in list(set(
            UserProfile(x) for x in [msg.from_user, msg.chat, msg.forward_from, msg.forward_from_chat, msg.via_bot]))]
        users.remove(None)
        for x in users:
            self.push_user(x)

    @staticmethod
    def get_msg_type(msg: Message) -> str:
        return 'photo' if msg.photo else \
            'video' if msg.video else \
            'animation' if msg.animation else \
            'document' if msg.document else \
            'text' if msg.text else \
            'voice' if msg.voice else 'error'

    @staticmethod
    def get_file_id(msg: Message, _type: str) -> str:
        return getattr(msg, _type).file_id

    #@staticmethod
    #def get_file_ref(msg: Message, _type: str) -> str:
    #    return getattr(msg, _type).file_ref


class CheckDuplicateMessage:
    def __init__(self, conn: PgSQLdb, delete: bool = False):
        # threading.Thread.__init__(self, daemon = True)
        self.msg: list[int] = []
        self.conn: PgSQLdb = conn
        self.delete: bool = delete

    def start(self):
        return asyncio.run_coroutine_threadsafe(self.run(), asyncio.get_event_loop())

    async def check(self) -> None:
        last_id = (await self.conn.query1('''SELECT "_id" FROM "index" ORDER BY "_id" DESC LIMIT 1'''))['_id']
        total_count = (await self.conn.query1('''SELECT COUNT(*) as "count" FROM "index" WHERE "_id" < %s''', last_id))[
            'count']
        await self.conn.execute('''TRUNCATE "dup_check"''')
        logger.debug('Last id is %d, total count: %d', last_id, total_count)
        for step in range(0, total_count, 200):  # type: ignore
            logger.debug('Current step: %d', step)
            while True:
                try:
                    sql_objx = await self.conn.query(
                        f'''SELECT "_id", "chat_id", "message_id", "from_user" 
                        FROM "index" WHERE "_id" < $1 OFFSET {step} LIMIT 200''',
                        last_id)
                    break
                except:
                    traceback.print_exc()
                    await asyncio.sleep(1)
            if len(sql_objx) == 0:
                break
            for sqlObj in sql_objx:
                _hash = self.get_hash(sqlObj)
                # print(_hash)
                await self.conn.execute('''INSERT INTO "dup_check" ("hash") VALUES ($1)''', _hash)
        # self.conn.commit()
        with open('pending_delete', 'w') as fout:
            fout.write(repr(self.msg))

    async def _delsql(self) -> None:
        async with aiofiles.open('pending_delete') as fin:
            ls = eval(await fin.read())
        for x in ls:
            await self.conn.execute('''DELETE FROM "index" WHERE "_id" = $1''', x)

    async def run(self) -> None:
        if self.delete:
            await self._delsql()
        else:
            await self.check()

    @staticmethod
    def get_hash(sql_obj: asyncpg.Record) -> str:
        return hashlib.sha256(
            ' '.join(map(str, (sql_obj['chat_id'], sql_obj['message_id'], sql_obj['from_user']))).encode()).hexdigest()
