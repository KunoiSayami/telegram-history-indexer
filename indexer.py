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
import asyncio
import logging
import os
import traceback
from configparser import ConfigParser
from typing import Dict, List, NoReturn, Optional, Sequence, Union

import pyrogram
import pyrogram.raw
import pyrogram.errors
from pyrogram import Client, ContinuePropagation
from pyrogram.types import Update, Message
from pyrogram.handlers import MessageHandler, RawUpdateHandler

import task
from libpy3.aiopgsqldb import PgSQLdb
from spider import iter_user_messages


class HistoryIndex:
    def __init__(self, client: Optional[Client] = None,
                 conn: Optional[PgSQLdb] = None,
                 other_client: Optional[Union[Client, bool]] = None):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(level=logging.DEBUG)

        config = ConfigParser()
        config.read('config.ini')

        self.filter_chat: List[int] = list(map(int, config['filters']['chat'].split(', ')))
        self.filter_user: List[int] = list(map(int, config['filters']['user'].split(', ')))

        self.logger.debug('Filter chat %s', repr(self.filter_chat))
        self.logger.debug('Filter user %s', repr(self.filter_user))

        self.other_client = other_client

        self.owner = int(config['account']['owner'])

        if client is None:
            self.client = Client(
                session_name='history_index',
                api_hash=config['account']['api_hash'],
                api_id=config['account']['api_id']
            )
            if isinstance(other_client, bool) and other_client:
                self.other_client=Client(
                    session_name='other_session',
                    api_hash=config['account']['api_hash'],
                    api_id=config['account']['api_id']
                )
        else:
            self.client = client

        if self.other_client is None:
            self.other_client = self.client

        self.bot_id = 0

        if conn is None:
            self.conn = PgSQLdb.create(
                config['pgsql']['host'],
                config.getint('pgsql', 'port'),
                config['pgsql']['username'],
                config['pgsql']['passwd'],
                config['pgsql']['database'],
            )
            self.bot_id = int(config['account']['indexbot_token'].split(':')[0])
            self._init = True
        else:
            self.conn = conn
            self._init = False

        self.media_lookup_channel = int(config['account']['media_send_target'])
        self.trackers = task.MsgTrackerThreadClass(
            self.client,
            self.conn,
            self.check_filter,
            notify = task.NotifyClass(self.other_client, self.owner),
            other_client = self.other_client,
        )

        self.client.add_handler(MessageHandler(self.pre_process), 888)
        self.client.add_handler(MessageHandler(self.handle_all_message), 888)
        self.client.add_handler(RawUpdateHandler(self.handle_raw_update), 999)

        self.index_dialog = iter_user_messages(self)

        self.logger.info('History indexer initialize success')

    def check_filter(self, msg: Message) -> bool:
        if msg.chat.id in self.filter_chat or \
                msg.forward_from and msg.forward_from.id in self.filter_user or \
                msg.from_user and msg.from_user.id in self.filter_user or \
                msg.scheduled:
            return True
        return False

    async def handle_raw_update(self, client: Client, update: Update, *_args) -> None:
        if isinstance(update, pyrogram.raw.types.UpdateDeleteChannelMessages):
            return self.trackers.push(update, True)
        if isinstance(update, pyrogram.raw.types.UpdateDeleteMessages):
            return self.trackers.push(update, True)
        if isinstance(update, (pyrogram.raw.types.UpdateUserName, pyrogram.raw.types.UpdateUserPhoto)):
            user_obj = client.get_users(update.user_id)
            return self.trackers.push_user(user_obj)
        if isinstance(update, pyrogram.raw.types.UpdateUserStatus) and \
                isinstance(update.status, (pyrogram.raw.types.UserStatusOffline, pyrogram.raw.types.UserStatusOnline)):
            return self.trackers.push(update, True)

    async def stop(self) -> None:
        self.trackers.work = False
        task = [asyncio.create_task(self.client.stop())]
        if self.client != self.other_client:
            task.append(asyncio.create_task(self.other_client.stop()))
        await asyncio.wait(task)
        if self._init:
            await self.conn.close()

    async def pre_process(self, _: Client, msg: Message) -> Optional[NoReturn]:
        if msg.text and msg.from_user and msg.from_user.id == self.bot_id and msg.text.startswith('/Magic'):
            await self.process_magic_function(msg)
        #if self.check_filter(msg): return
        if msg.chat.id == self.owner:
            return
        raise ContinuePropagation

    async def handle_all_message(self, _: Client, msg: Message) -> None:
        self.trackers.push(msg)

    async def start(self) -> None:
        self.logger.info('start indexer')
        tasks = []
        if self._init:
            await self.conn.init_connection()
        self.trackers.start()
        if self.other_client != self.client:
            self.logger.debug('Starting other client')
            tasks.append(asyncio.create_task(self.other_client.start()))
        self.logger.debug('Starting main watcher')
        tasks.append(asyncio.create_task(self.client.start()))
        self.logger.debug('telegram client: login.')
        await asyncio.wait(tasks)
        await self.index_dialog.recheck()

    async def get_media(self, msg: Message) -> None:
        str_array = msg.text.split()
        file_id, file_ref = '', ''
        if len(str_array) == 2:
            sql_obj = await self.conn.query1(
                '''SELECT "ref" FROM "file_ref" 
                WHERE "file_id" = %s AND "timestamp" >= DATE_SUB(NOW(), INTERVAL 115 MINUTE)''', str_array[1])
            if sql_obj is not None:
                file_id, file_ref = str_array[1], sql_obj['ref']
            else:
                return
            await self.client.send_cached_media(msg.chat.id, strs[1], sql_obj['ref'], f'/newcache {file_id} {file_ref}')

    async def process_magic_function(self, msg: Message) -> None:
        await asyncio.gather(msg.delete(), self.client.send(api.functions.messages.ReadHistory(peer=await self.client.resolve_peer(msg.chat.id), max_id=msg.message_id)))
        try:
            args = msg.text.split()
            if msg.text.startswith('/MagicForward'):
                await self.client.forward_messages('self', int(args[1]), int(args[2]), True)
            elif msg.text.startswith('/MagicGet'):
                await self.client.send_cached_media(msg.chat.id, args[1], f'/cache `{args[1]}`')
            elif msg.text.startswith('/MagicUpdateRef'):
                pass
            elif msg.text.startswith('/MagicDownload'):
                await self.client.download_media(args[1], file_name='avatar.jpg')
                await msg.reply_photo('downloads/avatar.jpg', False, f'/cache {" ".join(args[1:])}')
                os.remove('./downloads/avatar.jpg')
        except pyrogram.errors.RPCError:
            await self.client.send_message('self', f'<pre>{traceback.format_exc()}</pre>', 'html')


    async def idle(self) -> None:
        await pyrogram.idle()

if __name__ == "__main__":
    HistoryIndex(other_client=True).start()
