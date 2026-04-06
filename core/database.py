import sqlite3
import threading


class QueryTimeoutError(Exception):
    pass


class DatabaseManager:
    def __init__(self, db_path: str = ":memory:", query_timeout: float = 5.0):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.query_timeout = query_timeout

    def init_db(self):
        cursor = self.conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY,
                name TEXT,
                email TEXT,
                country TEXT,
                signup_date DATE
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER,
                product_name TEXT,
                amount FLOAT,
                order_date DATE,
                FOREIGN KEY(customer_id) REFERENCES customers(id)
            );
        """)
        self._seed_data(cursor)
        self.conn.commit()

    def _seed_data(self, cursor):
        cursor.execute("SELECT COUNT(*) FROM customers")
        if cursor.fetchone()[0] > 0:
            return

        customers = [
            (1, "Nguyen Van A", "a@mail.com", "Vietnam", "2024-01-15"),
            (2, "John Smith", "john@mail.com", "USA", "2024-03-20"),
            (3, "Tanaka Yuki", "yuki@mail.com", "Japan", "2024-06-10"),
            (4, "Tran Thi B", "b@mail.com", "Vietnam", "2024-09-01"),
            (5, "Maria Garcia", "maria@mail.com", "Spain", "2025-01-05"),
        ]
        cursor.executemany(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?)", customers
        )

        orders = [
            (1, 1, "Laptop", 1200.00, "2024-02-01"),
            (2, 1, "Mouse", 25.50, "2024-02-15"),
            (3, 2, "Keyboard", 75.00, "2024-04-10"),
            (4, 2, "Monitor", 450.00, "2024-05-20"),
            (5, 3, "Laptop", 1300.00, "2024-07-01"),
            (6, 3, "Headphones", 85.00, "2024-08-15"),
            (7, 4, "Phone", 800.00, "2024-10-01"),
            (8, 4, "Case", 15.00, "2024-10-05"),
            (9, 5, "Tablet", 600.00, "2025-02-01"),
            (10, 5, "Laptop", 1100.00, "2025-03-10"),
        ]
        cursor.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?)", orders
        )

    def execute(self, sql: str) -> tuple[list[str], list[tuple]]:
        result = {}

        def run_query():
            try:
                cursor = self.conn.cursor()
                cursor.execute(sql)
                result["columns"] = [desc[0] for desc in cursor.description]
                result["rows"] = cursor.fetchall()
            except Exception as e:
                result["error"] = e

        thread = threading.Thread(target=run_query)
        thread.start()
        thread.join(timeout=self.query_timeout)

        if thread.is_alive():
            self.conn.interrupt()
            thread.join()
            raise QueryTimeoutError(
                f"Query timed out after {self.query_timeout}s"
            )

        if "error" in result:
            raise result["error"]

        return result["columns"], result["rows"]

    def get_schema(self) -> str:
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]

        schema_parts = []
        for table in tables:
            cursor.execute(f"PRAGMA table_info({table})")
            cols = cursor.fetchall()
            col_defs = []
            for col in cols:
                col_def = f"  {col[1]} {col[2]}"
                if col[5]:
                    col_def += " PRIMARY KEY"
                col_defs.append(col_def)
            schema_parts.append(f"TABLE {table}:\n" + "\n".join(col_defs))

        return "\n\n".join(schema_parts)

    def get_data_context(self, sample_rows: int = 3) -> str:
        """Show sample rows from each table so LLM understands the actual data format."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]

        parts = []
        for table in tables:
            columns, rows = self.execute(f"SELECT * FROM {table} LIMIT {sample_rows}")
            header = " | ".join(columns)
            lines = [header, "-" * len(header)]
            for row in rows:
                lines.append(" | ".join(str(v) for v in row))
            parts.append(f"Sample from {table} ({sample_rows} rows):\n" + "\n".join(lines))

        return "\n\n".join(parts) if parts else ""

    def get_tables_data(self) -> dict:
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]

        result = {}
        for table in tables:
            columns, rows = self.execute(f"SELECT * FROM {table}")
            result[table] = {"columns": columns, "rows": rows}
        return result
