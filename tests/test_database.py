import pytest
from core.database import DatabaseManager


class TestDatabaseManager:
    def setup_method(self):
        self.db = DatabaseManager(":memory:")
        self.db.init_db()

    def test_init_creates_tables(self):
        cols, rows = self.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        table_names = [r[0] for r in rows]
        assert "customers" in table_names
        assert "orders" in table_names

    def test_seed_data_customers(self):
        cols, rows = self.db.execute("SELECT COUNT(*) FROM customers")
        assert rows[0][0] == 5

    def test_seed_data_orders(self):
        cols, rows = self.db.execute("SELECT COUNT(*) FROM orders")
        assert rows[0][0] == 10

    def test_execute_returns_columns_and_rows(self):
        cols, rows = self.db.execute("SELECT id, name FROM customers WHERE id = 1")
        assert cols == ["id", "name"]
        assert len(rows) == 1
        assert rows[0][1] == "Nguyen Van A"

    def test_execute_join(self):
        cols, rows = self.db.execute(
            "SELECT c.name, o.product_name FROM customers c "
            "JOIN orders o ON c.id = o.customer_id WHERE c.id = 1"
        )
        assert len(rows) == 2
        assert "name" in cols
        assert "product_name" in cols

    def test_execute_aggregation(self):
        cols, rows = self.db.execute(
            "SELECT country, COUNT(*) as cnt FROM customers GROUP BY country"
        )
        vietnam_row = [r for r in rows if r[0] == "Vietnam"]
        assert vietnam_row[0][1] == 2

    def test_execute_empty_result(self):
        cols, rows = self.db.execute("SELECT * FROM customers WHERE country = 'Antarctica'")
        assert rows == []
        assert len(cols) > 0

    def test_execute_sql_error(self):
        with pytest.raises(Exception):
            self.db.execute("SELECT * FROM nonexistent_table")

    def test_get_schema_contains_tables(self):
        schema = self.db.get_schema()
        assert "customers" in schema
        assert "orders" in schema
        assert "country" in schema
        assert "product_name" in schema

    def test_get_tables_data(self):
        data = self.db.get_tables_data()
        assert "customers" in data
        assert "orders" in data
        assert len(data["customers"]["rows"]) == 5
        assert len(data["orders"]["rows"]) == 10
        assert "columns" in data["customers"]
