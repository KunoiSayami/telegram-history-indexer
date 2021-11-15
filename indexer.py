# -*- coding: utf-8 -*-
# indexer.py
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
import ast
import asyncio
import logging
import os
import pathlib
import signal
from configparser import ConfigParser
from dataclasses import dataclass
from typing import List, NoReturn, Optional, Union

import pyrogram
import pyrogram.raw
import pyrogram.errors
from pyrogram import Client, ContinuePropagation
from pyrogram.types import Update, Message
from pyrogram.handlers import MessageHandler, RawUpdateHandler

import task
from sqlwrap import PgSQLdb
from spider import IterUserMessages


@dataclass
class ManagedDatabaseConnection:
    managed: bool
    conn: PgSQLdb


class HistoryIndex:
    def __init__(self,
                 config: ConfigParser,
                 conn: ManagedDatabaseConnection,
                 client: Optional[Client] = None,
                 other_client: Optional[Union[Client, bool]] = None):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(level=logging.DEBUG)

        self.filter_chat: List[int] = list(ast.literal_eval(config.get('filters', 'chat', fallback='()')))
        self.filter_user: List[int] = list(ast.literal_eval(config.get('filters', 'user', fallback='()')))

        self.logger.debug('Filter chat %s', repr(self.filter_chat))
        self.logger.debug('Filter user %s', repr(self.filter_user))

        self.other_client = other_client

        self.owner = config.getint('account', 'owner')

        self.managed_conn = conn
        self.conn = self.managed_conn.conn

        if client is None:
            self.client = Client(
                session_name='history_index',
                api_hash=config.get('account', 'api_hash'),
                api_id=config.get('account', 'api_id')
            )
            if isinstance(other_client, bool) and other_client:
                self.other_client = Client(
                    session_name='other_session',
                    api_hash=config.get('account', 'api_hash'),
                    api_id=config.get('account', 'api_id')
                )
        else:
            self.client = client

        if self.other_client is None:
            self.other_client = self.client

        self.bot_id = int(config.get('account', 'indexbot_token').split(':')[0])

        # self.media_lookup_channel = config.getint('account', 'media_send_target')

        if config.getboolean('file_store', 'enable', fallback=False):
            file_store = pathlib.Path(config.get('file_store', 'location'))
            if not file_store.exists():
                self.logger.info("Can't find %s, create it.", str(file_store))
                file_store.mkdir()
        else:
            file_store = None


        self.trackers = task.MsgTrackerThreadClass(
            self.client,
            self.conn,
            self.check_filter,
            notify=task.NotifyClass(self.other_client, self.owner),
            other_client=self.other_client,
            file_store=file_store
        )

        self.client.add_handler(MessageHandler(self.pre_process), 888)
        self.client.add_handler(MessageHandler(self.handle_all_message), 888)
        self.client.add_handler(RawUpdateHandler(self.handle_raw_update), 999)

        # TODO: Check this function availability #2
        #self.index_dialog = IterUserMessages(self)

        self.logger.info('History indexer initialize success')

    @classmethod
    async def create(cls,
                     conn: PgSQLdb | None = None,
                     client: Client | None = None,
                     other_client: Client | bool | None = None) -> HistoryIndex:
        config = ConfigParser()
        config.read('config.ini')
        if conn is None:
            conn = ManagedDatabaseConnection(True, await PgSQLdb.create(
                config.get('pgsql', 'host'),
                config.getint('pgsql', 'port'),
                config.get('pgsql', 'username'),
                config.get('pgsql', 'passwd'),
                config.get('pgsql', 'database'),
            ))
        else:
            conn = ManagedDatabaseConnection(False, conn)
        return cls(config, conn, client, other_client)

    def check_filter(self, msg: Message) -> bool:
        if msg.chat.id in self.filter_chat or \
                msg.forward_from and msg.forward_from.id in self.filter_user or \
                msg.from_user and msg.from_user.id in self.filter_user or \
                msg.scheduled:
            return True
        return False

    async def handle_raw_update(self, client: Client, update: Update, *_args) -> None:
        if isinstance(update, pyrogram.raw.types.UpdateDeleteChannelMessages):
            return self.trackers.push_no_user(update)
        if isinstance(update, pyrogram.raw.types.UpdateDeleteMessages):
            return self.trackers.push_no_user(update)
        if isinstance(update, (pyrogram.raw.types.UpdateUserName, pyrogram.raw.types.UpdateUserPhoto)):
            user_obj = await client.get_users(update.user_id)
            return self.trackers.push_user(user_obj)
        if isinstance(update, pyrogram.raw.types.UpdateUserStatus) and \
                isinstance(update.status, (pyrogram.raw.types.UserStatusOffline, pyrogram.raw.types.UserStatusOnline)):
            return self.trackers.push_no_user(update)

    async def stop(self) -> None:
        def sigkill(*_args):
            os.kill(os.getpid(), signal.SIGKILL)
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, sigkill)
        try:
            await self.trackers.stop()
        finally:
            tasks = [asyncio.create_task(self.client.stop())]
            if self.client != self.other_client:
                tasks.append(asyncio.create_task(self.other_client.stop()))
            await asyncio.wait(tasks)
            if self.managed_conn.managed:
                await self.conn.close()

    async def pre_process(self, _: Client, msg: Message) -> Optional[NoReturn]:
        # if msg.text and msg.from_user and msg.from_user.id == self.bot_id and msg.text.startswith('/Magic'):
        #     await self.process_magic_function(msg)
        if self.check_filter(msg):
            return
        if msg.chat.id == self.owner:
            return
        raise ContinuePropagation

    async def handle_all_message(self, _: Client, msg: Message) -> None:
        self.trackers.push(msg)

    async def start(self) -> bool:
        self.logger.info('start indexer')
        tasks = []
        self.trackers.start()
        if self.other_client != self.client:
            self.logger.debug('Starting other client')
            tasks.append(asyncio.create_task(self.other_client.start()))
        self.logger.debug('Starting main watcher')
        tasks.append(asyncio.create_task(self.client.start()))
        self.logger.debug('telegram client: login.')
        await asyncio.wait(tasks)
        # TODO: #2
        # await self.index_dialog.recheck()
        self.logger.debug('Indexer: started.')
        return True

    # async def get_media(self, msg: Message) -> None:
    #     str_array = msg.text.split()
    #     file_id, file_ref = '', ''
    #     if len(str_array) == 2:
    #         sql_obj = await self.conn.query1(
    #             '''SELECT "ref" FROM "file_ref"
    #             WHERE "file_id" = $1 AND "timestamp" >= DATE_SUB(NOW(), INTERVAL 115 MINUTE)''', str_array[1])
    #         if sql_obj is not None:
    #             file_id, file_ref = str_array[1], sql_obj['ref']
    #         else:
    #             return
    #         await self.client.send_cached_media(
    #             msg.chat.id, str_array[1], f'/newcache {file_id} {file_ref}')

    # async def process_magic_function(self, msg: Message) -> None:
    #     await asyncio.gather(msg.delete(), self.client.send(
    #         pyrogram.raw.functions.messages.ReadHistory(
    #             peer=await self.client.resolve_peer(msg.chat.id),
    #             max_id=msg.message_id)))
    #     try:
    #         args = msg.text.split()
    #         if msg.text.startswith('/MagicForward'):
    #             await self.client.forward_messages('self', int(args[1]), int(args[2]), True)
    #         elif msg.text.startswith('/MagicGet'):
    #             await self.client.send_cached_media(msg.chat.id, args[1], f'/cache `{args[1]}`')
    #         elif msg.text.startswith('/MagicUpdateRef'):
    #             pass
    #         elif msg.text.startswith('/MagicDownload'):
    #             await self.client.download_media(args[1], file_name='avatar.jpg')
    #             await msg.reply_photo('downloads/avatar.jpg', False, f'/cache {" ".join(args[1:])}')
    #             os.remove('./downloads/avatar.jpg')
    #     except pyrogram.errors.RPCError:
    #         await self.client.send_message('self', f'<pre>{traceback.format_exc()}</pre>', 'html')

    async def idle(self) -> None:
        await self.trackers.idle()


async def main():
    index_instance = await HistoryIndex.create(other_client=True)
    await index_instance.start()
    try:
        await index_instance.idle()
    finally:
        await index_instance.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
