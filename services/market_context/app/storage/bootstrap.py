"""Idempotent DB/user provisioning for both existing and new Compose volumes."""
import os

import pymysql


def main():
    connection = pymysql.connect(host='db', user='root', password=os.environ['MARIADB_ROOT_PASSWORD'], autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute('CREATE DATABASE IF NOT EXISTS market_context CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
            cursor.execute("CREATE USER IF NOT EXISTS 'market_context'@'%%' IDENTIFIED BY %s", (os.environ['MARKET_CONTEXT_DB_PASSWORD'],))
            cursor.execute("GRANT ALL PRIVILEGES ON market_context.* TO 'market_context'@'%'")
        print('Market Context database/user available')
    finally:
        connection.close()


if __name__ == '__main__':
    main()
