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
from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from typing import Callable

import pyrogram.errors
from pyrogram import Client
from pyrogram.types import Message, User, Chat

import sqlwrap
import utils
from custom_type import UserProfile


class IndexUserMessages:
    MAGIC_ALL_USER_DIALOG_INDEXED = -7
    MAGIC_ALL_GROUP_OR_CHANNEL_INDEXED = -2
    MAGIC_INIT_FLAG = -6

    def __init__(self, client: Client, conn: sqlwrap.PgSQLdb, user_checker: Callable[[User], None]):

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

        self.client = client
        self.conn = conn
        self.user_checker = user_checker
        self.end_time: int = 0

    async def run(self):
        while not self.client.is_connected:
            await asyncio.sleep(0.01)
        self.logger.debug('Running reindex function')
        await self.init()
        await self.process_each_dialog()

    async def init(self) -> None:
        ret = await self.conn.query_last_index_message(self.MAGIC_INIT_FLAG)
        if ret and ret.is_indexed:
            return
        self.logger.debug('initializing spider database')
        await self.conn.insert_last_index_message(self.MAGIC_INIT_FLAG, 0, False)

        # TODO: No flood wait here, is this ok?
        async for dialog in self.client.iter_dialogs(offset_date=ret.last_message_id if ret else 0):
            await self.conn.insert_last_index_message(dialog.chat.id, dialog.top_message.message_id)
            if not dialog.is_pinned:
                await self.conn.update_last_index_message(self.MAGIC_INIT_FLAG, dialog.top_message.date)

        await self.conn.update_last_index_message_flag(self.MAGIC_INIT_FLAG, True)
        self.logger.info('Spider database initialized')

    async def process_each_dialog(self) -> bool:
        self.logger.debug('Process each dialogs')
        current_dialog = await self.conn.query_last_not_index_chat()
        if current_dialog is None:
            return True
        while current_dialog:
            await self.index_dialog(current_dialog, self.end_time)
            current_dialog = await self.conn.query_last_not_index_chat()
        return False

    async def index_dialog(self, dialog: sqlwrap.MessageIndex, date_limit: int = 0) -> None:
        self.logger.info('Reindexing %d', dialog.chat_id)
        offset_id = dialog.last_message_id
        if isinstance(chat := await self.client.get_chat(dialog.chat_id), Chat):
            self.user_checker(chat)
        apply_date_limit = True
        if date_limit > 0 and \
                await self.conn.query_count_before_date(
                    dialog.chat_id, datetime.fromtimestamp(date_limit)) < 100:
            self.logger.info("Can't find message before specify date, query full history")
            apply_date_limit = False
        while offset_id > 1:
            while True:
                try:
                    hist = await self.client.get_history(dialog.chat_id, offset_id=offset_id)
                    await self.conn.insert_many_message([self.parse_msg(msg) for msg in hist])
                    doc_msgs = []
                    for msg in hist:
                        if msg.media and (ret := self.parse_document_msg(msg)):
                            doc_msgs.append(ret)
                    if len(doc_msgs):
                        await self.conn.insert_many_documents(doc_msgs)
                    await self.conn.update_last_index_message(dialog.chat_id, offset_id)
                    break
                except pyrogram.errors.FloodWait as e:
                    self.logger.warning('Got FloodWait, wait %d seconds', e.x)
                    await asyncio.sleep(e.x)
                    continue
            if dialog.chat_id < 0:
                users = set()
                for msg in hist:
                    _users = list(set(
                        UserProfile(x) for x in
                        [msg.from_user, msg.chat, msg.forward_from, msg.forward_from_chat, msg.via_bot]))
                    for user in _users:
                        users.add(user)
                for user in users:
                    if user is None:
                        continue
                    self.user_checker(user.raw)
            try:
                if apply_date_limit and hist[-1].date < date_limit:
                    break
                offset_id = hist[-1].message_id
            except IndexError:
                break
            print(f'\r{dialog.chat_id}', f'{offset_id:6}', end='')
        print()
        await self.conn.update_last_index_message_flag(dialog.chat_id, True)
        self.logger.info('Index %d completed', dialog.chat_id)

    @classmethod
    def parse_document_msg(cls, msg: Message) -> tuple[int, int, int, int | None, str, str, str, datetime] | tuple[
        int, int, int, int | None, str, datetime
    ] | None:
        _type = utils.get_msg_type(msg)
        if _type == 'text':
            return None
        base = cls.parse_msg(msg)
        if _type == 'error':
            return None
        file_id = utils.get_file_id(msg, _type)
        return *base[:4], msg.caption, _type, file_id, base[-1],

    @classmethod
    def parse_msg(cls, msg: Message) -> tuple[int, int, int, int | None, str, datetime]:
        text = msg.text if not msg.media else msg.caption
        if text is None:
            text = ''
        return (
            msg.chat.id,
            msg.message_id,
            msg.from_user.id if msg.from_user else msg.chat.id,
            cls.get_forward_from(msg),
            text,
            datetime.fromtimestamp(msg.date)
        )

    @staticmethod
    def get_forward_from(msg: Message) -> int | None:
        if msg.forward_sender_name:
            forward_from_id = -1001228946795
        else:
            forward_from_id = msg.forward_from.id if msg.forward_from else \
                msg.forward_from_chat.id if msg.forward_from_chat else None
        return forward_from_id

    async def reindex(self) -> None:
        if self.end_time is None:
            date = int((await self.conn.query_last_record_message_date()).timestamp())
        else:
            self.logger.debug('Override last record message time to: %d', self.end_time)
            date = self.end_time
        if date is None:
            return
        offset_date = date - 600
        async for dialog in self.client.iter_dialogs():
            await self.index_dialog(sqlwrap.MessageIndex.from_dialog(dialog), offset_date)
            if dialog.top_message.date < offset_date:
                break
