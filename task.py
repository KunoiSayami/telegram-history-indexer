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
import logging
import signal
import time
import traceback
from abc import ABCMeta, abstractmethod
from pathlib import Path
from typing import Callable

import asyncpg
import pyrogram
import pyrogram.errors
from pyrogram import Client
from pyrogram.types import Chat, Message, User
from pyrogram.raw.types import UpdateDeleteChannelMessages, UpdateDeleteMessages, UpdateUserStatus, \
    UpdateUserName, UpdateUserPhoto

from custom_type import UserProfile
from sqlwrap import PgSQLdb
from spider import IndexUserMessages
import utils

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
            await self.client.send_message(self.target, f'```{msg}```', 'markdown')
        except pyrogram.errors.RPCError:
            traceback.print_exc()
        finally:
            self.last_send = time.time()
        return True


class MediaDownloader:
    def __init__(self, client: Client, conn: PgSQLdb, stop_signal: asyncio.Event, file_store: Path):
        self.client: Client = client
        self.conn: PgSQLdb = conn
        self.download_queue: asyncio.Queue = asyncio.Queue()
        self.stop_signal: asyncio.Event = stop_signal
        self.file_store = file_store

    def push(self, file_id: str, timestamp: datetime.datetime):
        self.download_queue.put_nowait((file_id, timestamp.replace(microsecond=0)))

    def start(self) -> concurrent.futures.Future:
        return asyncio.run_coroutine_threadsafe(self.run(), asyncio.get_event_loop())

    async def run(self) -> None:
        logger.debug('Download thread is ready to get file.')
        while not self.stop_signal.is_set():
            task = asyncio.create_task(self.download_queue.get())
            while not self.stop_signal.is_set():
                result, _pending = await asyncio.wait([task], timeout=1)
                if len(result) > 0:
                    await self.download(*result.pop().result())
                    break
                if self.stop_signal.is_set():
                    task.cancel()
                    return
        logger.debug('Download thread stopped!')

    async def download(self, file_id: str, timestamp: datetime.datetime) -> None:
        if ret := await self.conn.query_media(file_id):
            img_path = self.file_store.joinpath('archive', str(ret.year), str(ret.month), f'{file_id}.jpg')
            if img_path.exists():
                return
        else:
            img_path = self.file_store.joinpath('archive', str(timestamp.year), str(timestamp.month), f'{file_id}.jpg')
        if not img_path.parent.exists():
            img_path.parent.mkdir(parents=True)
        try:
            await self.client.download_media(file_id, str(img_path))
        except pyrogram.errors.UnknownError:
            logger.exception('Got Unknown error')
        except pyrogram.errors.RPCError:
            logger.error('Got rpc error while downloading %s(%d)', file_id, timestamp.timestamp())


class MsgTrackerThreadClass:
    def __init__(self, client: Client, conn: PgSQLdb, filter_func: Callable[[Message], bool], *,
                 notify: SendMethod | None = None, other_client: Client | None = None,
                 file_store: Path | None = None):
        # super().__init__(daemon=True)

        self.msg_queue: asyncio.Queue = asyncio.Queue()
        self.user_queue: asyncio.Queue = asyncio.Queue()
        self.client: Client = client
        self.conn: PgSQLdb = conn
        self.other_client: Client | None = other_client
        self.filter_func: Callable[[Message], bool] = filter_func
        if self.other_client is None:
            self.other_client = self.client
        self.notify = notify
        if self.notify is None:
            self.notify = FakeNotifyClass()
        self.emergency_mode: bool = False
        self.futures: list[concurrent.futures.Future] = []
        self.stop_event: asyncio.Event = asyncio.Event()
        self.file_store = file_store
        self.media_downloader = MediaDownloader(self.client, self.conn, self.stop_event, self.file_store)
        self.index_dialog = IndexUserMessages(self.client, self.conn, self.push_user)

    def start(self) -> None:
        logger.debug('Starting `MsgTrackerThreadClass\'')
        self.futures.append(asyncio.run_coroutine_threadsafe(self.index_dialog.run(), asyncio.get_event_loop()))
        self.futures.append(asyncio.run_coroutine_threadsafe(self.user_tracker(), asyncio.get_event_loop()))
        self.futures.append(asyncio.run_coroutine_threadsafe(self.run(), asyncio.get_event_loop()))
        if self.file_store is not None:
            self.futures.append(self.media_downloader.start())
        logger.debug('Start `MsgTrackerThreadClass\' successful')

    async def stop(self) -> None:
        self.stop_event.set()
        notified = False
        logger.info('Waiting all futures to stop.')
        await asyncio.sleep(1)
        for future in self.futures:
            if future.running() and not notified:
                logger.warning('Future still running, waiting more time to until it finished')
                notified = True
            for _ in range(3):
                if future.running():
                    await asyncio.sleep(1.5)
                else:
                    break
            if future.running():
                logger.warning('Future still running after period of time, cancel it.')
                future.cancel()
            try:
                future.result(0)
            except asyncpg.PostgresError:
                logger.exception('Got database exception')
            except (concurrent.futures.CancelledError, concurrent.futures.TimeoutError):
                pass
        logger.debug('stopped!')

    async def run(self) -> None:
        logger.debug('`msg_tracker_thread\' started!')
        while not self.client.is_connected:
            await asyncio.sleep(.05)
        while not self.stop_event.is_set():
            task = asyncio.create_task(self.msg_queue.get())
            while True:
                done, _pending = await asyncio.wait([task], timeout=1)
                if len(done):
                    try:
                        await self.filter_msg(done.pop().result())
                    except asyncpg.PostgresError:
                        logger.error('Got database exception, raise it.')
                        raise
                    break
                if self.stop_event.is_set():
                    task.cancel()
                    return
        logger.debug('Exit!')

    async def filter_msg(self, msg: Message) -> None:
        if await self.process_updates(msg):
            return
        if self.filter_func(msg):
            return
        try:
            await self._filter_msg(msg)
        except (pyrogram.errors.RPCError, asyncpg.PostgresError):
            await self.notify.send(traceback.format_exc())

    async def _filter_msg(self, msg: Message) -> None:
        if msg.new_chat_members:
            await self.conn.execute(
                '''INSERT INTO "group_history" 
                ("chat_id", "user_id", "message_id", "history_date") VALUES ($1, $2, $3, $4)''',
                [(msg.chat.id, x.id, msg.message_id, datetime.datetime.fromtimestamp(msg.date)) for x in
                 msg.new_chat_members], many=True)
            return

        text = msg.text if msg.text else msg.caption if msg.caption else ''

        if text.startswith('/') and not text.startswith('//'):
            return

        _type = utils.get_msg_type(msg)
        if _type == 'error':
            if text == '':
                return
            _type = 'text'
        file_id = utils.get_file_id(msg, _type)

        if msg.edit_date is not None:
            if _type == 'text':
                sql_obj = await self.conn.query1_msg(msg.chat.id, msg.message_id)
            else:
                sql_obj = await self.conn.query1_doc(msg.chat.id, msg.message_id)
            if sql_obj is not None:
                if text == sql_obj['body']:
                    return
                if _type == 'text':
                    await self.conn.update_msg_body(msg.chat.id, msg.message_id, text)
                else:
                    await self.conn.update_doc_body(msg.chat.id, msg.message_id, text, file_id)
                if msg.edit_date != 0:
                    await self.conn.insert_edit_record(
                        msg.chat.id,
                        msg.from_user.id if msg.from_user else msg.chat.id,
                        msg.message_id,
                        sql_obj['body'],
                        datetime.datetime.fromtimestamp(msg.edit_date)
                    )
                else:
                    logger.debug('Find message edit date is 0: %s', repr(msg))
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

        try:
            await self.conn.insert_message(
                msg.chat.id,
                msg.message_id,
                msg.from_user.id if msg.from_user else msg.chat.id,
                forward_from_id,
                text,
                datetime.datetime.fromtimestamp(msg.date)
            )
        except asyncpg.UniqueViolationError:
            result = await self.conn.query1_msg(msg.chat.id, msg.message_id)
            logger.debug('Found unique violation error, %d %d %s', msg.chat.id, msg.message_id, str(result))

        if _type != 'text':
            # FIXME: FIX THE FXXK WRONG ORDER
            await self.conn.execute(
                '''INSERT INTO "document_index"
                 ("chat_id", "message_id", "from_user", "forward_from", "body", "message_date", "doc_type", "file_id")
                 VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT ("chat_id", "message_id")
                 DO UPDATE SET "body" = $5, "file_id" = $8''',
                msg.chat.id,
                msg.message_id,
                msg.from_user.id if msg.from_user else msg.chat.id,
                forward_from_id,
                text if len(text) > 0 else None,
                datetime.datetime.fromtimestamp(msg.date),
                _type,
                file_id
            )
            if msg.photo and (msg.from_user and not msg.from_user.is_bot):
                self.media_downloader.push(file_id, datetime.datetime.fromtimestamp(msg.date))
        # logger.debug("INSERT TO \"index\" %d %d %s", msg.chat.id, msg.message_id, text)

    async def _insert_delete_record(self, chat_id: int, msgs: list[int]) -> None:
        sz = [(chat_id, x) for x in msgs]
        await self.conn.execute(
            '''INSERT INTO "deleted_message" ("chat_id", "message_id") VALUES ($1, $2)''',
            sz, many=True
        )
        base = Path('archive')
        archive = Path('deleted')
        for message_id in msgs:
            if ret := await self.conn.query1_doc(chat_id, message_id):
                # if ret['doc_type'] == 'photo' and (date := await self.conn.query_media_date(ret['file_id'])):
                if date := await self.conn.query_media_date(ret['file_id']):
                    media_base = Path(str(date.year), str(date.month), f'{ret["file_id"]}.jpg')
                    media_path = self.file_store.joinpath(base, media_base)
                    if media_path.exists():
                        if not (target := Path(archive, media_base)).parent.exists():
                            target.parent.mkdir(parents=True)
                        media_path.rename(Path(archive, media_base))
                        logger.info('Move %s.jpg to archive', ret['file_id'])

    async def process_updates(
            self,
            update: UpdateUserStatus | UpdateDeleteMessages | UpdateDeleteChannelMessages | Message
    ) -> bool:
        # Process delete message
        if isinstance(update, pyrogram.raw.types.UpdateDeleteMessages):
            sql_obj = None
            for x in update.messages:
                sql_obj = await self.conn.query1(
                    '''SELECT "chat_id" FROM "message_index" WHERE "message_id" = $1 AND "chat_id" > 0''', x)
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

    async def idle(self) -> None:
        _idle = asyncio.Event()

        def _reset_idle(*_args):
            _idle.set()

        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(sig, _reset_idle)
        while not _idle.is_set():
            for future in self.futures:
                try:
                    if (e := future.exception(0)) is not None:
                        raise e
                except (pyrogram.errors.RPCError, asyncpg.PostgresError):
                    logger.exception('Got Telegram or database exception, raising')
                    raise
                except (concurrent.futures.CancelledError, concurrent.futures.TimeoutError):
                    pass
                if _idle.is_set():
                    break
            await asyncio.sleep(1)

    async def user_tracker(self) -> None:
        logger.debug('`user_tracker\' started!')
        while not self.client.is_connected:
            await asyncio.sleep(.1)
        while not self.stop_event.is_set():
            while self.user_queue.empty():
                await asyncio.sleep(.1)
                if self.stop_event.is_set():
                    break
            await self._user_tracker()
        if not self.user_queue.empty():
            await self._user_tracker()

    async def _user_tracker(self) -> None:
        while not self.user_queue.empty():
            await self._real_user_index(self.user_queue.get_nowait())

    async def insert_username(self, user: User | Chat) -> None:
        if user.username is None:
            return
        sql_obj = await self.conn.query1(
            '''SELECT "username" FROM "username_history" WHERE "user_id" = $1 
            ORDER BY "entry_id" DESC LIMIT 1''',
            user.id
        )
        if sql_obj and sql_obj['username'] == user.username:
            return
        await self.conn.execute(
            '''INSERT INTO "username_history" ("user_id", "username") VALUES ($1, $2)''',
            user.id, user.username
        )

    async def _real_user_index(self, user: User | Chat, *, enable_request: bool = False) -> bool:
        if user is None:
            return False
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
            await user_profile.exec_sql(self.conn)
            if user_profile.photo_id:
                self.media_downloader.push(user_profile.photo_id, datetime.datetime.now())
            return True
        if peer_id != sql_obj['peer_id']:
            await self.conn.execute(
                '''UPDATE "user_index" SET "peer_id" = $1 WHERE "user_id" = $2''',
                peer_id, user_profile.user_id)
        if user_profile.hash != sql_obj['hash']:
            await self.conn.execute(
                '''UPDATE "user_index" SET 
                "first_name" = $1, "last_name" = $2, "photo_id" = $3, "hash" = $4, "peer_id" = $5, 
                "update_time" = CURRENT_TIMESTAMP WHERE "user_id" = $6''',
                user_profile.first_name,
                user_profile.last_name,
                user_profile.photo_id,
                user_profile.hash,
                peer_id,
                user_profile.user_id,
            )
            await user_profile.exec_sql(self.conn)
            if user_profile.photo_id:
                self.media_downloader.push(user_profile.photo_id, datetime.datetime.now())
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
