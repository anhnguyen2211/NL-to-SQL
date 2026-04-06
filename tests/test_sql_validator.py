import pytest
from core.sql_validator import validate_and_enforce


class TestValidateAndEnforce:
    # --- Valid queries ---
    def test_simple_select(self):
        result = validate_and_enforce("SELECT * FROM users")
        assert "SELECT" in result.upper()
        assert "LIMIT" in result.upper()

    def test_select_with_existing_limit(self):
        result = validate_and_enforce("SELECT * FROM users LIMIT 50")
        assert "LIMIT 50" in result.upper()

    def test_limit_capped_to_max(self):
        result = validate_and_enforce("SELECT * FROM users LIMIT 500", max_rows=100)
        assert "LIMIT 100" in result.upper()

    def test_select_with_join(self):
        result = validate_and_enforce(
            "SELECT c.name, o.amount FROM customers c JOIN orders o ON c.id = o.customer_id"
        )
        assert "SELECT" in result.upper()

    def test_select_with_aggregation(self):
        result = validate_and_enforce(
            "SELECT country, COUNT(*) FROM customers GROUP BY country"
        )
        assert "SELECT" in result.upper()

    def test_strips_trailing_semicolon(self):
        result = validate_and_enforce("SELECT * FROM users;")
        assert ";" not in result

    # --- Invalid queries ---
    def test_empty_string(self):
        with pytest.raises(ValueError, match="[Ee]mpty"):
            validate_and_enforce("")

    def test_whitespace_only(self):
        with pytest.raises(ValueError, match="[Ee]mpty"):
            validate_and_enforce("   ")

    def test_delete_blocked(self):
        with pytest.raises(ValueError, match="SELECT"):
            validate_and_enforce("DELETE FROM users")

    def test_drop_blocked(self):
        with pytest.raises(ValueError, match="SELECT"):
            validate_and_enforce("DROP TABLE users")

    def test_insert_blocked(self):
        with pytest.raises(ValueError, match="SELECT"):
            validate_and_enforce("INSERT INTO users VALUES (1, 'a')")

    def test_update_blocked(self):
        with pytest.raises(ValueError, match="SELECT"):
            validate_and_enforce("UPDATE users SET name = 'a'")

    def test_create_blocked(self):
        with pytest.raises(ValueError, match="SELECT"):
            validate_and_enforce("CREATE TABLE foo (id INT)")

    def test_multiple_statements_blocked(self):
        with pytest.raises(ValueError, match="[Ss]ingle|[Oo]ne|[Mm]ultiple"):
            validate_and_enforce("SELECT 1; SELECT 2")

    def test_malformed_sql(self):
        with pytest.raises(ValueError):
            validate_and_enforce("SELEKT * FORM users")
