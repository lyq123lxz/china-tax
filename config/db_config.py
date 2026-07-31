"""
config/db_config.py
PostgreSQL 与 SQLite 双模持久化数据库连接管理模块 (Python 3.14+ 强类型)
"""

import os
import json
import sqlite3
from pathlib import Path
from typing import Any

# 项目根目录
BASE_DIR = Path(__file__).parent.parent.resolve()
DB_DIR = BASE_DIR / "data"
DB_PATH = DB_DIR / "china_tax.db"
SETTINGS_PATH = DB_DIR / "db_settings.json"

class DBCursor:
    """统一的数据库游标包装器，用于适配 SQLite 占位符 '?' 与 PostgreSQL 占位符 '%s'"""
    def __init__(self, cursor: Any, is_pg: bool) -> None:
        self.cursor = cursor
        self.is_pg = is_pg

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        if self.is_pg:
            # 将 SQLite 的 '?' 占位符转换为 PostgreSQL 的 '%s' 占位符
            sql_pg = sql.replace("?", "%s")
            return self.cursor.execute(sql_pg, params)
        else:
            return self.cursor.execute(sql, params)

    def fetchall(self) -> list[Any]:
        return self.cursor.fetchall()

    def fetchone(self) -> Any:
        return self.cursor.fetchone()

    def close(self) -> None:
        self.cursor.close()

    def __enter__(self) -> "DBCursor":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

class DBConnection:
    """统一的数据库连接包装器，屏蔽底层的 SQLite 和 PostgreSQL API 差异"""
    def __init__(self, conn: Any, is_pg: bool) -> None:
        self.conn = conn
        self.is_pg = is_pg

    def cursor(self) -> DBCursor:
        return DBCursor(self.conn.cursor(), self.is_pg)

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "DBConnection":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            self.rollback()
        self.close()

DEFAULT_SETTINGS = {
    "db_mode": "sqlite",
    "pg_host": "localhost",
    "pg_port": 5432,
    "pg_dbname": "china-tax",
    "pg_user": "postgres",
    "pg_password": ""
}

def load_settings() -> dict[str, Any]:
    """从本地读取数据库存储配置"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)

def save_settings(settings: dict[str, Any]) -> None:
    """将数据库存储配置保存至本地"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)

def init_db(conn_to_init: Any = None) -> None:
    """初始化数据库表结构 (自动适配 SQLite 与 PostgreSQL 语法差异)"""
    if conn_to_init is not None:
        conn = conn_to_init
        is_pg = conn.is_pg
    else:
        conn = get_connection()
        is_pg = conn.is_pg

    try:
        with conn.cursor() as cursor:
            if is_pg:
                # PostgreSQL 表结构
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tax_records (
                        id SERIAL PRIMARY KEY,
                        taxpayer_name VARCHAR(255) NOT NULL,
                        credit_code VARCHAR(50) NOT NULL,
                        income VARCHAR(50) NOT NULL,
                        deductions VARCHAR(50) NOT NULL,
                        tax_payable VARCHAR(50) NOT NULL,
                        tax_type VARCHAR(50) NOT NULL,
                        created_at VARCHAR(50) NOT NULL
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS history_archives (
                        id SERIAL PRIMARY KEY,
                        archive_name VARCHAR(255) NOT NULL,
                        file_path VARCHAR(512) NOT NULL,
                        operator VARCHAR(100) NOT NULL,
                        created_at VARCHAR(50) NOT NULL
                    )
                """)
            else:
                # SQLite 表结构
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tax_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        taxpayer_name TEXT NOT NULL,
                        credit_code TEXT NOT NULL,
                        income TEXT NOT NULL,
                        deductions TEXT NOT NULL,
                        tax_payable TEXT NOT NULL,
                        tax_type TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS history_archives (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        archive_name TEXT NOT NULL,
                        file_path TEXT NOT NULL,
                        operator TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
            conn.commit()
    except Exception as e:
        print(f"[DB Init Error] Failed to initialize tables (is_pg={is_pg}): {e}")
    finally:
        if conn_to_init is None:
            conn.close()

def get_connection() -> DBConnection:
    """获取当前活动数据库模式的封装连接实例"""
    settings = load_settings()
    db_mode = settings.get("db_mode", "sqlite")

    if db_mode == "postgresql":
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=settings.get("pg_host", "localhost"),
                port=int(settings.get("pg_port", 5432)),
                database=settings.get("pg_dbname", "china-tax"),
                user=settings.get("pg_user", "postgres"),
                password=settings.get("pg_password", ""),
                connect_timeout=3
            )
            return DBConnection(conn, is_pg=True)
        except Exception as e:
            print(f"[DB Engine Error] Failed to connect to PostgreSQL: {e}. Falling back to SQLite.")
            # 回退至 SQLite

    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15.0)
    return DBConnection(conn, is_pg=False)

async def test_pg_connection(host: str, dbname: str, user: str, port: int, password: str = "") -> dict[str, Any]:
    """异步物理测试 PostgreSQL 的连通性，且若是初次配置，则一并同步生成表结构"""
    import asyncio
    def _test():
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=host,
                database=dbname,
                user=user,
                port=port,
                password=password,
                connect_timeout=3
            )
            # 测试能否写入结构
            temp_conn = DBConnection(conn, is_pg=True)
            init_db(temp_conn)
            temp_conn.close()
            return {"success": True, "message": f"物理连接测试成功，且对应表结构已一并初始化完毕！(主机: {host}, 数据库: {dbname})"}
        except ImportError:
            return {
                "success": False,
                "message": "物理连接测试失败：驱动 (psycopg2) 未安装，请检查系统环境"
            }
        except Exception as err:
            return {"success": False, "message": f"物理连接测试失败: {str(err)}"}

    return await asyncio.to_thread(_test)
