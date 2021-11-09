# -*- coding: utf-8 -*-
# type_custom.py
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
from dataclasses import dataclass
import datetime
import hashlib
import warnings
from typing import TypeVar

from pyrogram.types import Chat, User

import libpy3.aiopgsqldb

_vT = TypeVar('_vT', str, int, float)


class SimpleUserProfile:
    def __init__(self, user: User | Chat | None):
        self.raw: User | Chat = user
        self.user_id: int | None = user.id if user is not None else None

    def __hash__(self):
        return hash(self.user_id)

    def __eq__(self, sup):
        return self.user_id == sup.user_id


class UserProfile(SimpleUserProfile):
    def __init__(self, user: User | Chat | None):
        super().__init__(user)
        if user is None:
            return
        # self.username = user.username if user.username else None
        self.photo_id: str | None = user.photo.big_file_id if user.photo else None

        if isinstance(user, Chat) and user.type not in ('private', 'bot'):
            self.full_name: str = user.title
            self.first_name: str = user.title

            self.last_name: str | None = None
        else:
            self.first_name: str = user.first_name
            self.last_name: str | None = user.last_name if user.last_name else None
            self.full_name: str = '{} {}'.format(self.first_name, self.last_name) \
                if self.last_name else self.first_name

        if self.full_name is None:
            warnings.warn(
                'Caught None first name',
                RuntimeWarning
            )
            self.full_name: str = ''

        self.hash = hashlib.sha256(','.join((
            str(self.user_id),
            self.full_name,
            self.photo_id if self.photo_id else ''
        )).encode()).hexdigest()

        if isinstance(user, User):
            self.sql_insert = (
                '''INSERT INTO "user_history" ("user_id", "first_name", "last_name", "full_name", "photo_id") 
                VALUES ($1, $2, $3, $4, $5)''',
                (
                    self.user_id,
                    # self.username,
                    self.first_name,
                    self.last_name,
                    self.full_name,
                    self.photo_id,
                )
            )
        else:
            self.sql_insert = (
                '''INSERT INTO "user_history" ("user_id", "first_name", "full_name", "photo_id") 
                VALUES ($1, $2, $3, $4)''',
                (
                    self.user_id,
                    # self.username,
                    self.full_name,
                    self.full_name,
                    self.photo_id,
                )
            )

    async def exec_sql(self, instance: libpy3.aiopgsqldb.PgSQLdb) -> None:
        await instance.execute(self.sql_insert[0], *self.sql_insert[1])

class HashableUser:
    def __init__(self,
                 user_id: int,
                 first_name: str,
                 last_name: str | None = None,
                 photo_id: str | None = None,
                 **_kwargs):
        self.user_id: int = user_id
        self.first_name: str = first_name
        self.last_name: str | None = last_name
        self.full_name: str = '{} {}'.format(first_name, last_name) if last_name else first_name
        self.photo_id: str | None = photo_id

    def get_dict(self) -> dict[str, _vT]:
        return {'user_id': self.user_id, 'full_name': self.full_name}

    def __hash__(self) -> int:
        return hash(self.user_id)

    def __eq__(self, user_obj: HashableUser) -> bool:
        return self.user_id == user_obj.user_id


class HashableMessageRecord:
    def __init__(self,
                 chat_id: int,
                 from_user: int,
                 message_id: int,
                 text: str,
                 timestamp: datetime.datetime,
                 **_kwargs):
        self.chat_id: int = chat_id
        self.from_user: int = from_user
        self.message_id: int = message_id
        self.text: str = text
        self.timestamp: datetime.datetime = timestamp

    def get_dict(self) -> dict[str, _vT]:
        return {'user_id': self.from_user, 'text': self.text, 'timestamp': self.timestamp,
                'message_id': self.message_id}

    def __hash__(self) -> int:
        return hash((self.chat_id, self.message_id))

    def __eq__(self, message_obj: HashableMessageRecord) -> bool:
        return self.chat_id == message_obj.chat_id and self.message_id == message_obj.message_id


@dataclass(init=False)
class SQLCache:
    cache_id: int
    step: int | None
    cache: str | None
    settings_hash: str | None

    def __init__(self,
                 _id: int,
                 step: int | None = None,
                 cache: str | None = None,
                 settings_hash: str | None = None):
        self.cache_id = _id
        self.step = step
        self.cache = cache
        self.settings_hash = settings_hash

    def __repr__(self) -> str:
        return 'type_sql_cache(_id = %d, step = %s, settings_hash = %s, cache = %s)' % (
            self.cache_id, self.step, self.settings_hash, len(eval(self.cache)) if self.cache is not None else None
        )
