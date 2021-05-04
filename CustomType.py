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
from dataclasses import dataclass
import datetime
import hashlib
import warnings
from typing import Dict, Optional, Tuple, TypeVar, Union

from pyrogram import Chat, User

_vT = TypeVar('_vT', str, int, float)

class SimpleUserProfile:
    def __init__(self, user: Optional[Union[User, Chat]]):
        self.raw: Union[User, Chat] = user
        self.user_id: Optional[int] = user.id if user != None else None

    def __hash__(self):
        return hash(self.user_id)

    def __eq__(self, sup):
        return self.user_id == sup.user_id


class UserProfile(SimpleUserProfile):
    def __init__(self, user: Optional[Union[User, Chat]]):
        super().__init__(user)
        if user is None: return
        #self.username = user.username if user.username else None
        self.photo_id: Optional[str] = user.photo.big_file_id if user.photo else None

        if isinstance(user, Chat) and user.type not in ('private', 'bot'):
            self.full_name: str = user.title
            self.first_name: str = user.title

            self.last_name: Optional[str] = None
        else:
            self.first_name: str = user.first_name
            self.last_name: Optional[str] = user.last_name if user.last_name else None
            self.full_name: str = '{} {}'.format(self.first_name, self.last_name) if self.last_name else self.first_name

        if self.full_name is None:
            warnings.warn(
                'Caughted None first name',
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
                "INSERT INTO `user_history` (`user_id`, `first_name`, `last_name`, `full_name`, `photo_id`) VALUE (%s, %s, %s, %s, %s)",
                (
                    self.user_id,
                    #self.username,
                    self.first_name,
                    self.last_name,
                    self.full_name,
                    self.photo_id,
                )
            )
        else:
            self.sql_insert = (
                "INSERT INTO `user_history` (`user_id`, `first_name`, `full_name`, `photo_id`) VALUE (%s, %s, %s, %s)",
                (
                    self.user_id,
                    #self.username,
                    self.full_name,
                    self.full_name,
                    self.photo_id,
                )
            )
    @property
    def sql_statement(self) -> str:
        return self.sql_insert[0]

    @property
    def sql_args(self) -> Tuple[Optional[Union[int, str]], ...]:
        return self.sql_insert[1]


class HashableUser:
    def __init__(self, user_id: int, first_name: str, last_name: Optional[str] = None, photo_id: Optional[str] = None, **_kwargs):
        self.user_id: int = user_id
        self.first_name: str = first_name
        self.last_name: Optional[str] = last_name
        self.full_name: str = '{} {}'.format(first_name, last_name) if last_name else first_name
        self.photo_id: Optional[str] = photo_id

    def get_dict(self) -> Dict[str, _vT]:
        return {'user_id': self.user_id, 'full_name': self.full_name}

    def __hash__(self) -> int:
        return hash(self.user_id)

    def __eq__(self, userObj) -> bool:
        return self.user_id == userObj.user_id


class HashableMessageRecord:
    def __init__(self, chat_id: int, from_user: int, message_id: int, text: str, timestamp: datetime.datetime, **_kwargs):
        self.chat_id: int = chat_id
        self.from_user: int = from_user
        self.message_id: int = message_id
        self.text: str = text
        self.timestamp: datetime.datetime = timestamp

    def get_dict(self) -> Dict[str, _vT]:
        return {'user_id': self.from_user, 'text': self.text, 'timestamp': self.timestamp, 'message_id': self.message_id}

    def __hash__(self) -> int:
        return hash((self.chat_id, self.message_id))

    def __eq__(self, messageObj: 'HashableMessageRecord') -> bool:
        return self.chat_id == messageObj.chat_id and self.message_id == messageObj.message_id


@dataclass(init=False)
class SQLCache:
    cache_id: int
    step: Optional[int]
    cache: Optional[str]
    settings_hash: Optional[str]


    def __init__(self, _id: int, step: Optional[int] = None, cache: Optional[str] = None, settings_hash: Optional[str] = None):
        self.cache_id = _id
        self.step = step
        self.cache = cache
        self.settings_hash = settings_hash

    def __repr__(self) -> str:
        return 'type_sql_cache(_id = %d, step = %s, settings_hash = %s, cache = %s)'%(
            self.cache_id, self.step, self.settings_hash, len(eval(self.cache)) if self.cache is not None else None
        )
