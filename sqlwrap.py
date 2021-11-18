# -*- coding: utf-8 -*-
# sqlwrap.py
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
import datetime
from dataclasses import dataclass
from typing import Generator

import asyncpg

from pyrogram.types import Dialog

from libpy3.aiopgsqldb import PgSQLdb as _PgSQLdb


@dataclass
class MessageIndex:
    chat_id: int
    last_message_id: int
    is_indexed: bool

    @classmethod
    def from_dialog(cls, dialog: Dialog) -> MessageIndex:
        return cls(dialog.chat.id, dialog.top_message.message_id, False)

    @classmethod
    def from_record(cls, record: asyncpg.Record | None) -> MessageIndex | None:
        if record is None:
            return None
        return cls(record['chat_id'], record['last_message_id'], record['is_indexed'])


class PgSQLdb(_PgSQLdb):

    async def query1_msg(self, chat_id: int, message_id: int) -> asyncpg.Record:
        return await self.query1(
            '''SELECT "body" FROM "message_index" WHERE "chat_id" = $1 AND "message_id" = $2''',
            chat_id, message_id
        )

    async def query1_doc(self, chat_id: int, message_id: int) -> asyncpg.Record:
        return await self.query1(
            '''SELECT "body" FROM "document_index" WHERE "chat_id" = $1 AND "message_id" = $2''',
            chat_id, message_id
        )

    async def insert_edit_record(self, chat_id: int, from_user: int,
                                 message_id: int, body: str, edit_date: datetime.datetime):
        await self.execute(
            '''INSERT INTO "edit_history" ("chat_id" , "from_user", "message_id", "body", "edit_date") 
             VALUES ($1, $2, $3, $4, $5)''',
            chat_id,
            from_user,
            message_id,
            body,
            edit_date
        )

    async def update_msg_body(self, chat_id: int, message_id: int, body: str | None) -> None:
        if body is None:
            body = ''
        await self.execute(
            '''UPDATE "message_index" SET "body" = $1 WHERE "chat_id" = $2 AND "message_id" = $3''',
            body, chat_id, message_id
        )

    async def update_doc_body(self, chat_id: int, message_id: int, body: str, file_id: str) -> None:
        await asyncio.gather(
            self.execute(
                '''UPDATE "document_index" SET "body" = $1, "file_id" = $2 
                 WHERE "chat_id" = $3 AND "message_id" = $4''',
                body, file_id, chat_id, message_id
            ),
            self.update_msg_body(chat_id, message_id, body)
        )

    async def insert_message(self, chat_id: int, message_id: int, from_user: int, forward_from: int,
                             body: str, message_date: datetime.datetime) -> None:

        await self.execute(
            '''INSERT INTO "message_index"
             ("chat_id", "message_id", "from_user", "forward_from", "body", "message_date")
             VALUES ($1, $2, $3, $4, $5, $6)''',
            chat_id,
            message_id,
            from_user,
            forward_from,
            body,
            message_date
        )

    async def insert_media(self, file_id: str, timestamp: datetime.datetime) -> None:
        await self.execute(
            '''INSERT INTO "media_mapping" VALUES ($1, $2)''',
            file_id,
            timestamp
        )

    async def query_media(self, file_id: str) -> datetime.datetime | None:
        ret = await self.query1(
            '''SELECT "media_time" FROM "media_mapping" WHERE "file_id" = $1''',
            file_id
        )
        if ret:
            return ret['media_time']
        return None

    async def query_last_message(self, chat_id: int) -> int | None:
        ret = await self.query1(
            '''SELECT "message_id" FROM "message_index" WHERE "chat_id" = $1''',
            chat_id
        )
        if ret:
            return ret['message_id']
        return None

    async def query_last_index_message(self, chat_id: int) -> MessageIndex | None:
        ret = await self.query1(
            '''SELECT "last_message_id", "is_indexed" FROM "history_index" WHERE "chat_id" = $1''',
            chat_id
        )
        if ret:
            return MessageIndex(chat_id, ret['last_message_id'], ret['is_indexed'])
        return None

    async def insert_last_index_message(self, chat_id: int, message_id: int, is_indexed: bool = False) -> None:
        await self.execute(
            '''INSERT INTO "history_index" VALUES ($1, $2, $3) 
             ON CONFLICT ("chat_id") DO UPDATE SET "last_message_id" = $2, "is_indexed" = $3''',
            chat_id,
            message_id,
            is_indexed,
        )

    async def update_last_index_message(self, chat_id: int, message_id: int) -> None:
        await self.execute(
            '''UPDATE "history_index" SET "last_message_id" = $1 WHERE "chat_id" = $2''',
            message_id,
            chat_id
        )

    async def update_last_index_message_flag(self, chat_id: int, is_indexed: bool) -> None:
        await self.execute(
            '''UPDATE "history_index" SET "is_indexed" = $1 WHERE "chat_id" = $2''',
            is_indexed,
            chat_id
        )

    async def query_last_not_index_chat(self) -> MessageIndex | None:
        ret = await self.query1(
            '''SELECT * FROM "history_index" WHERE "is_indexed" = false AND ("chat_id" < -10 OR "chat_id" > 0)'''
        )
        return MessageIndex.from_record(ret)

    async def insert_many_message(self, args: list[tuple[int, int, int, int, str, datetime.datetime]]) -> None:
        await self.execute(
            '''INSERT INTO "message_index" VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING ''',
            args,
            many=True
        )

    async def insert_many_documents(self, args: list[tuple[int, int, int, int, str, datetime.datetime]]) -> None:
        await self.execute(
            '''INSERT INTO "document_index" 
                ("chat_id", "message_id", "from_user", "forward_from", "body", "doc_type", "file_id", "message_date")
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT DO NOTHING ''',
            args,
            many=True
        )

    async def iter_dialogs(self) -> Generator[int, None, None]:
        cut = (await self.query1(
            '''SELECT COUNT(*) FROM "history_index"'''
        ))['COUNT(*)']
        for limit in range(0, cut, 100):
            for item in await self.query('''SELECT "chat_id" FROM "history_index" LIMIT {},50'''.format(limit)):
                yield item['chat_id']

    async def query_last_record_message_date(self) -> datetime.datetime | None:
        ret = await self.query1('''SELECT "message_date" FROM "message_index" ORDER BY "message_date" DESC LIMIT 1''')
        if ret:
            return ret['message_date']
        return None

    async def query_count_before_date(self, chat_id: int, date: datetime.datetime) -> int:
        return (await self.query1(
            '''SELECT COUNT(*) FROM "message_index" WHERE "message_date" < $1 AND "chat_id" = $2''',
            date, chat_id))['count']

    async def query_media_date(self, file_id: str) -> datetime.datetime | None:
        ret = await self.query1(
            '''SELECT "media_time" FROM "media_mapping" WHERE "file_id" = $1 AND "archive" = false''',
            file_id)
        if ret:
            return ret['media_time']
        return None

    async def update_media_archive_flag(self, file_id: str, flag: bool) -> None:
        await self.execute(
            '''UPDATE "media_mapping" SET "archive" = $1 WHERE "file_id" = $2''', flag, file_id
        )

