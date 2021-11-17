# -*- coding: utf-8 -*-
# utils.py
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
from pyrogram.types import Message


def get_msg_type(msg: Message) -> str:
    return 'photo' if msg.photo else \
        'video' if msg.video else \
        'animation' if msg.animation else \
        'document' if msg.document else \
        'text' if msg.text else \
        'voice' if msg.voice else 'error'


def get_file_id(msg: Message, _type: str) -> str | None:
    if _type == 'text':
        return None
    return getattr(msg, _type).file_id
