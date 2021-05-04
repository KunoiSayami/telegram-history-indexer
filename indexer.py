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
from pyrogram import (Client, ContinuePropagation, Message, MessageHandler,
                      RawUpdateHandler, Update, api)

import task
from libpy3.aiomysqldb import MySqlDB
from spider import iter_user_messages


class HistoryIndex:
    def __init__(self, client: Optional[Client] = None,
                 conn: Optional[MySqlDB] = None,
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
            self.conn = MySqlDB(
                config['mysql']['host'],
                config['mysql']['username'],
                config['mysql']['passwd'],
                config['mysql']['history_db'],
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
        if isinstance(update, pyrogram.api.types.UpdateDeleteChannelMessages):
            return self.trackers.push(update, True)
        if isinstance(update, pyrogram.api.types.UpdateDeleteMessages):
            return self.trackers.push(update, True)
        if isinstance(update, (pyrogram.api.types.UpdateUserName, pyrogram.api.types.UpdateUserPhoto)):
            userObj = client.get_users(update.user_id)
            return self.trackers.push_user(userObj)
        if isinstance(update, pyrogram.api.types.UpdateUserStatus) and \
                isinstance(update.status, (pyrogram.api.types.UserStatusOffline, pyrogram.api.types.UserStatusOnline)):
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

    @staticmethod
    def _parse_html_user(user_id: int, username: Union[str, int, Dict[str, str]]) -> str:
        if isinstance(username, dict):
            username = username['full_name']
        if username is None:
            username = user_id
        return f'<a href="tg://user?id={user_id}">{username}</a>'

    async def process_magic_send_ex(self, msg: Message) -> None:
        args: Sequence[str] = msg.text.split()[1:]
        await self.client.send_message(
            int(args[0]),
            args[1].format(
                *(
                    self._parse_html_user(
                        x,
                        await self.conn.query1(
                            'SELECT `full_name` FROM `user_history` WHERE `user_id` = %s ORDER BY `_id` DESC',
                            x
                        )
                    ) for x in args[2:]
                )
            ),
            'html',
            True
        )

    async def process_magic_send(self, msg: Message) -> None:
        args = msg.text.split()[1:]
        await self.client.send_message(
            int(args[0]),
            args[1].format(
                *(self._parse_html_user(args[2:][x], args[2:][x + 1]) for x in range(0, len(args[2:]), 2))
            ),
            'html',
            True
        )

    async def pull_messages(self, msg: Message) -> None:
        pass

    async def get_media(self, msg: Message) -> None:
        strs = msg.text.split()
        file_id, file_ref = '', ''
        if len(strs) == 2:
            sql_obj = await self.conn.query1("SELECT `ref` FROM `file_ref` WHERE `file_id` = %s AND `timestamp` >= DATE_SUB(NOW(), INTERVAL 115 MINUTE)", strs[1])
            if sql_obj is not None:
                file_id, file_ref = strs[1], sql_obj['ref']
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
                await msg.reply_photo('downloads/avatar.jpg', None, False, f'/cache {" ".join(args[1:])}')
                os.remove('./downloads/avatar.jpg')
            elif msg.text.startswith('/MagicSendEx'):
                await self.process_magic_send_ex(msg)
            elif msg.text.startswith('/MagicSend'):
                await self.process_magic_send(msg)
            elif msg.text.startswith('/MagicQuery'):
                await self.pull_messages(msg.text)
        except pyrogram.errors.RPCError:
            await self.client.send_message('self', f'<pre>{traceback.format_exc()}</pre>', 'html')


    async def idle(self) -> None:
        await self.client.idle()

if __name__ == "__main__":
    HistoryIndex(other_client=True).start()
