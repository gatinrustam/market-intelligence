"""Idempotent DB/user provisioning for both existing and new Compose volumes."""
import os

import pymysql


def main():
    connection = pymysql.connect(host='db', user='root', password=os.environ['MARIADB_ROOT_PASSWORD'], autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute('CREATE DATABASE IF NOT EXISTS article_semantic CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
            cursor.execute("CREATE USER IF NOT EXISTS 'article_semantic'@'%%' IDENTIFIED BY %s", (os.environ['ARTICLE_SEMANTIC_DB_PASSWORD'],))
            cursor.execute("GRANT ALL PRIVILEGES ON article_semantic.* TO 'article_semantic'@'%'")
        print('Article semantic database/user available')
    finally:
        connection.close()


if __name__ == '__main__':
    main()
