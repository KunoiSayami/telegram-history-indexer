# -*- coding: utf-8 -*-
# type_user.py
# Copyright (C) 2019 KunoiSayami
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
from pyrogram import User, Chat
import warnings
import hashlib

class simple_user_profile(object):
	def __init__(self, user: User or Chat or None):
		self.raw = user
		self.user_id = user.id if user != None else None
	def __hash__(self):
		return hash(self.user_id)
	def __eq__(self, sup):
		return self.user_id == sup.user_id

class user_profile(simple_user_profile):
	def __init__(self, user: User or Chat or None):
		simple_user_profile.__init__(self, user)
		if user is None: return
		#self.username = user.username if user.username else None
		self.photo_id = user.photo.big_file_id if user.photo else None

		if isinstance(user, Chat) and user.type not in ('private', 'bot'):
			self.first_name = self.full_name = user.title
			self.last_name = None
		else:
			self.first_name = user.first_name
			self.last_name = user.last_name if user.last_name else None
			self.full_name = '{} {}'.format(self.first_name, self.last_name) if self.last_name else self.first_name
		
		if self.full_name is None:
			warnings.warn(
				'Caughted None first name',
				RuntimeWarning
			)
			self.full_name = ''

		self.hash = hashlib.sha256(','.join((
			str(self.user_id),
			self.full_name,
			self.photo_id if self.photo_id else ''
		)).encode()).hexdigest()

		if isinstance(user, User):
			self.sql_insert = (
				"INSERT INTO `user_history` (`user_id`, `first_name`, `last_name`, `photo_id`) VALUE (%s, %s, %s, %s)",
				(
					self.user_id,
					#self.username,
					self.first_name,
					self.last_name,
					self.photo_id,
				)
			)
		else:
			self.sql_insert = (
				"INSERT INTO `user_history` (`user_id`, `first_name` , `photo_id`) VALUE (%s, %s, %s)",
				(
					self.user_id,
					#self.username,
					self.full_name,
					self.photo_id,
				)
			)

class hashable_user(object):
	def __init__(self, user_id: int, first_name: str, last_name: str or None = None, photo_id: str or None = None, **_kwargs):
		self.user_id = user_id
		self.first_name = first_name
		self.last_name = last_name
		self.full_name = '{} {}'.format(first_name, last_name) if last_name else first_name
		self.photo_id = photo_id
	def get_dict(self):
		return {'user_id': self.user_id, 'full_name': self.full_name}
	def __hash__(self):
		return hash(self.user_id)
	def __eq__(self, userObj):
		return self.user_id == userObj.user_id