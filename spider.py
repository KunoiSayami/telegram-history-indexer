# -*- coding: utf-8 -*-
# spider.py
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
import concurrent.futures
import logging
import traceback
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pyrogram.errors
from pyrogram import Dialog, Message, User


class iter_user_messages:
    def __init__(self, indexer):
        #threading.Thread.__init__(self, daemon = True)

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

        self.client = indexer.client
        self.conn = indexer.conn
        self.indexer = indexer
        self.end_time = 0

    def run(self):
        #self._process_messages(-, )
        self.get_dialogs()
        self.process_messages()

    async def _indenify_user(self, users: List[User]):
        userinfos = await self.client.get_users(users)
        for x in userinfos:
            self.indexer.trackers.user_queue.put_nowait(x)

    async def indenify_user(self):
        sql_obj = await self.conn.query("SELECT `user_id` FROM `indexed_dialogs` WHERE `user_id` > 1")
        users = [x['user_id'] for x in sql_obj]
        while len(users) > 200:
            await self._indenify_user(users[:200])
            users = users[200:]
        await self._indenify_user(users)

    async def get_dialogs(self):
        sql_obj = await self.conn.query1("SELECT `last_message_id`, `indexed` FROM `indexed_dialogs` WHERE `user_id` = -1")
        if sql_obj is None:
            offset_date, switch = 0, True
        else:
            offset_date, switch = sql_obj['last_message_id'], sql_obj['indexed'] != 'Y'
        while switch:
            try:
                dialogs = await self.client.get_dialogs(offset_date)
                await self.process_dialogs(dialogs, sql_obj)
                await asyncio.sleep(5)
                offset_date = dialogs[-1].top_message.date - 1
                sql_obj = await self.conn.query1("SELECT `last_message_id`, `indexed` FROM `indexed_dialogs` WHERE `user_id` = -1")
            except pyrogram.errors.FloodWait as e:
                self.logger.warning('Caughted Flood wait, wait %d seconds', e.x)
                await asyncio.sleep(e.x)
            except IndexError:
                break
        if switch:
            await self.indenify_user()
        self.logger.debug('Search over')

    async def process_dialogs(self, dialogs: List[Dialog], sql_obj: Optional[Dict]):
        for dialog in dialogs:
            try:
                await self.conn.execute("INSERT INTO `indexed_dialogs` (`user_id`, `last_message_id`) VALUE (%s, %s)", (dialog.chat.id, dialog.top_message.message_id))
            except:
                print(traceback.format_exc().splitlines()[-1])
            await self.indexer.user_profile_track(dialog.top_message)
        try:
            if sql_obj:
                await self.conn.execute("UPDATE `indexed_dialogs` SET `last_message_id` = %s WHERE `user_id` = -1", (dialogs[-1].top_message.date - 1, ))
            else: # If None
                await self.conn.execute("INSERT INTO `indexed_dialogs` (`user_id`, `last_message_id`) VALUE (%s, %s)", (-1, dialogs[-1].top_message.date - 1))
        except IndexError:
            if sql_obj:
                await self.conn.execute("UPDATE `indexed_dialogs` SET `indexed` = 'Y' WHERE `user_id` = -1")
            else:
                await self.conn.execute("INSERT INTO `indexed_dialogs` (`user_id`,`indexed`, `last_message_id`) VALUE (-1, 'Y', 0)")
            raise

    async def process_messages(self) -> None:
        while True:
            sql_obj = await self.conn.query1("SELECT * FROM `indexed_dialogs` WHERE `indexed` = 'N' AND `user_id` > 1 LIMIT 1")
            if sql_obj is None: break
            if await self.conn.query1("SELECT * FROM `user_index` WHERE `user_id` = %s AND `is_bot` = 'Y'", (sql_obj['user_id'],)):
                self.conn.execute("UPDATE `indexed_dialogs` SET `indexed` = 'Y' WHERE `user_id` = %s", (sql_obj['user_id'],))
                continue
            await self.conn.execute("UPDATE `indexed_dialogs` SET `started_indexed` = 'Y' WHERE `user_id` = %s", (sql_obj['user_id'],))
            #self.conn.commit()
            await self._process_messages(sql_obj['user_id'], sql_obj['last_message_id'])
            await self.conn.execute("UPDATE `indexed_dialogs` SET `indexed` = 'Y' WHERE `user_id` = %s", (sql_obj['user_id'],))

    async def _process_messages(self, user_id: int, offset_id: int, *, force_check: bool = False) -> None:
        while offset_id > 1:
            self.logger.debug('Current process %d %d',user_id, offset_id)
            while True:
                try:
                    msg_his = await self.client.get_history(user_id, offset_id=offset_id)
                    break
                except pyrogram.errors.FloodWait as e:
                    self.logger.warning('got FloodWait, wait %d seconds', e.x)
                    await asyncio.sleep(e.x)
            if self.__process_messages(msg_his, force_check):
                break
            try:
                offset_id = msg_his[-1].message_id - 1
            except IndexError:
                break
            await asyncio.sleep(5)

    def __process_messages(self, msg_group: List[Message], force_check: bool = False) -> bool:
        for x in msg_group:
            if force_check: x.edit_date = 0
            self.indexer.trackers.msg_queue.put_nowait(x)
            if x.date < self.end_time:
                return True
        return False

    async def recheck(self, force_check: bool = False) -> None:
        sql_obj = await self.conn.query1("SELECT `timestamp` FROM `index` ORDER BY `timestamp` DESC LIMIT 1")
        self.logger.debug('Rechecking...')
        if force_check or (sql_obj and (datetime.now() - sql_obj['timestamp']).total_seconds() > 60 * 30):
            if isinstance(self.end_time, int) and self.end_time == 0:
                self.end_time = sql_obj['timestamp'].replace(tzinfo=timezone.utc).timestamp()
            if isinstance(self.end_time, datetime):
                self.end_time = self.end_time.replace(tzinfo=timezone.utc).timestamp()

            self.logger.info('Calling recheck function')
            self.logger.debug('Endtime is %d', self.end_time)

            #threading.Thread(target = self._recheck, daemon = True).start()
            self.bootstrap_recheck()

            self.logger.debug('Recheck function start successful')
        else:
            self.logger.info('Nothing to recheck')

    def bootstrap_recheck(self) -> concurrent.futures.Future:
        return asyncio.run_coroutine_threadsafe(self._recheck(), asyncio.get_event_loop())

    async def _recheck(self):
        while not self.client.is_connected:
            await asyncio.sleep(0.01)
        offset_date = 0
        chats = []
        while True:
            try:
                dialogs = await self.client.get_dialogs(offset_date)
                for x in dialogs.dialogs:
                    if x.top_message.date < self.end_time:
                        raise IndexError
                    chats.append((x.chat.id, x.top_message.message_id))
                offset_date = dialogs.dialogs[-1].top_message.date - 1
            except pyrogram.errors.FloodWait as e:
                self.logger.warning('Caughted Flood wait, wait %d seconds', e.x)
                await asyncio.sleep(e.x)
            except IndexError:
                break
        self.logger.info('Find %d chats', len(chats))
        self.logger.debug('chats (%s)', repr(chats))
        for x in chats:
            await self._process_messages(x[0], x[1], force_check=True)
