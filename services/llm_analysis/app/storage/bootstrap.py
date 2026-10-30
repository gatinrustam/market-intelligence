"""Idempotent DB/user provisioning for both existing and new Compose volumes."""
import os

import pymysql


def main():
    connection = pymysql.connect(host='db', user='root', password=os.environ['MARIADB_ROOT_PASSWORD'], autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute('CREATE DATABASE IF NOT EXISTS llm_analysis CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
            cursor.execute("CREATE USER IF NOT EXISTS 'llm_analysis'@'%%' IDENTIFIED BY %s", (os.environ['LLM_ANALYSIS_DB_PASSWORD'],))
            cursor.execute("GRANT ALL PRIVILEGES ON llm_analysis.* TO 'llm_analysis'@'%'")
        print('LLM Analysis database/user available')
    finally:
        connection.close()


if __name__ == '__main__':
    main()
