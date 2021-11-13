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

import asyncpg

from pyrogram.types import Message

from libpy3.aiopgsqldb import PgSQLdb as _PgSQLdb


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
