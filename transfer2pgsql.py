#!/usr/bin/env python
# -*- coding: utf-8 -*-
# transfer2pgsql.py
# Copyright (C) 2019-2021 KunoiSayami
#
# This module is part of telegram-history-indexer and is released under
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
import asyncpg
import aiomysql
import asyncio
from configparser import ConfigParser

from typing import Callable, Tuple, Union, Any, Optional

config = ConfigParser()
config.read('config.ini')
host = config.get('mysql', 'host')
port = config.get('pgsql', 'port')  # only for pgsql
muser = config.get('mysql', 'username')
mpasswd = config.get('mysql', 'passwd')
puser = config.get('pgsql', 'username')
ppasswd = config.get('pgsql', 'passwd')
mdatabase = config.get('mysql', 'history_db')
pdatabase = config.get('pgsql', 'database')



async def main() -> None:
    pgsql_connection = await asyncpg.connect(host='127.0.0.1', port=port, user=puser, password=ppasswd, database=pdatabase)
    mysql_connection = await aiomysql.create_pool(
        host=host,
        user=muser,
        password=mpasswd,
        db=mdatabase,
        charset='utf8mb4',
        cursorclass=aiomysql.cursors.Cursor,
    )
    if input('Do you want to delete all data? [y/N]: ').strip().lower() == 'y':
        await clean(pgsql_connection)
        print('Clear database successfully')
    else:
        print('Skipped clear database')
    async with mysql_connection.acquire() as conn:
        async with conn.cursor() as cursor:
            await exec_and_insert(cursor, "SELECT * FROM deleted_message", pgsql_connection,
                                  '''INSERT INTO "deleted_message" VALUES ($1, $2, $3)''', bigdata=True)
            await exec_and_insert(cursor, "SELECT * FROM document_index", pgsql_connection,
                                  '''INSERT INTO "document_index" VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT DO NOTHING''', transfer2, True)
            await exec_and_insert(cursor, "SELECT * FROM edit_history", pgsql_connection,
                                  '''INSERT INTO "edit_history" VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING''', bigdata=True)
            await exec_and_insert(cursor, "SELECT * FROM group_history", pgsql_connection,
                                  '''INSERT INTO "group_history" VALUES ($1, $2, $3, $4)  ON CONFLICT DO NOTHING''', transfer2, True)
            await exec_and_insert(cursor, "SELECT * FROM `index`", pgsql_connection,
                                  '''INSERT INTO "message_index" VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING''', message_index_transfer, True)
            await exec_and_insert(cursor, "SELECT * FROM online_records", pgsql_connection,
                                  '''INSERT INTO "online_record" VALUES ($1, $2, $3)''', transfer, bigdata=True)
            await exec_and_insert(cursor, "SELECT * FROM user_history", pgsql_connection,
                                  '''INSERT INTO "user_history" VALUES ($1, $2, $3, $4, $5, $6, $7)   ON CONFLICT DO NOTHING''', transfer4,  bigdata=True)
            await exec_and_insert(cursor, "SELECT * FROM user_index", pgsql_connection,
                                  '''INSERT INTO "user_index" VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)  ON CONFLICT DO NOTHING''', transfer3, bigdata=True)
            await exec_and_insert(cursor, "SELECT * FROM username_history", pgsql_connection,
                                  '''INSERT INTO "username_history" VALUES ($1, $2, $3, $4)   ON CONFLICT DO NOTHING''', bigdata=True)
    await pgsql_connection.close()
    mysql_connection.close()
    await mysql_connection.wait_closed()


def str2bool(x: str) -> bool:
    return x == 'Y'


def transfer(obj: Tuple[int, str, str, str]) -> Tuple[Union[bool, Any], ...]:
    return tuple(map(lambda x: str2bool(x) if isinstance(x, str) else x, obj))


def transfer2(obj):
    print(obj[1:])
    return obj[1:]


def get_table_name(sql: str) -> str:
    return sql.split("\"", maxsplit=3)[1]


def transfer4(obj):
    return obj[0], str(obj[1]), obj[2], obj[3], obj[4], obj[5], obj[6]


def transfer3(obj: Tuple[int, str, str, str]) -> Tuple[Union[bool, Any], ...]:
    return tuple((*obj[:6], str2bool(obj[6]), str2bool(obj[7]), *obj[8:]))

def transfer5(obj):
    obj = transfer3(obj)
    return str(obj[1]), *obj[2:]


def message_index_transfer(obj):
    obj = obj[1:]
    return obj[0], obj[3], obj[1], obj[2], obj[4], obj[5]

def print_all(obj):
    print(obj)
    return obj


async def exec_and_insert(cursor, sql: str, pg_connection, insert_sql: str,
                          process: Callable[[Any], Any] = None, bigdata: bool = False) -> None:
    print('Processing table:', sql[13:])
    real_table_name = get_table_name(insert_sql)
    try:
        if await pg_connection.fetchrow(f'SELECT * FROM "{real_table_name}" LIMIT 1') is not None:
            if input(f'Table {real_table_name} has data, do you still want to process insert? [y/N]: ').strip().lower() != 'y':
                return
            if input(f'Table {real_table_name} has data, do you want to truncate it? [y/N]: ').strip().lower() != 'y':
                await pg_connection.execute(f'''TRUNCATE "{real_table_name}"''')
    except asyncpg.UndefinedTableError:
        pass
    if bigdata:
        step = 0
        await cursor.execute(f'SELECT count(*) FROM {sql[14:]}')
        total = (await cursor.fetchone())[0]
        await cursor.execute(f'{sql} LIMIT {step}, 1000')
        obj = await cursor.fetchall()
        while True:
            print(f'\rtotal: {total}, step: {step}, process: {(step/total) * 100:.2f}', end='')
            if process is not None:
                queue = [pg_connection.executemany(insert_sql, list(process(o) for o in obj))]
            else:
                queue = [pg_connection.executemany(insert_sql, list(obj))]
            if len(obj) == 1000:
                await cursor.execute(f'{sql} LIMIT {step + 1000}, 1000')
                queue.append(cursor.fetchall())
            rt = await asyncio.gather(*queue)
            if len(obj) < 1000:
                print()
                break
            if len(rt) > 1:
                obj = rt[1]
            step += 1000
        print()
    else:
        await cursor.execute(sql)
        obj = await cursor.fetchall()
        for sql_obj in obj:
            if process is not None:
                sql_obj = process(sql_obj)
            await pg_connection.execute(insert_sql, *sql_obj)


async def clean(pgsql_connection: asyncpg.connection) -> None:
    await pgsql_connection.execute('''TRUNCATE "deleted_message"''')
    await pgsql_connection.execute('''TRUNCATE "document_index"''')
    await pgsql_connection.execute('''TRUNCATE "edit_history"''')
    await pgsql_connection.execute('''TRUNCATE "group_history"''')
    await pgsql_connection.execute('''TRUNCATE "index"''')
    await pgsql_connection.execute('''TRUNCATE "online_records"''')
    await pgsql_connection.execute('''TRUNCATE "user_history"''')
    await pgsql_connection.execute('''TRUNCATE "user_index"''')
    await pgsql_connection.execute('''TRUNCATE "username_history"''')


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())