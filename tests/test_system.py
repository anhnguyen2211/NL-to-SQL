import pytest
from unittest.mock import MagicMock
from core.system import NLToSQLSystem
from core.sql_validator import validate_and_enforce
from core.database import DatabaseManager


class TestNLToSQLSystem:
    def setup_method(self):
        self.db = DatabaseManager(":memory:")
        self.db.init_db()
        self.mock_llm = MagicMock()
        self.system = NLToSQLSystem(
            llm=self.mock_llm,
            validator=validate_and_enforce,
            db=self.db,
        )

    def test_ask_returns_sql_result(self):
        self.mock_llm.generate_sql.return_value = {
            "type": "sql",
            "sql": "SELECT COUNT(*) FROM customers",
            "explanation": "Count all customers",
        }
        self.mock_llm.interpret_result.return_value = {
            "answer": "There are 5 customers.",
            "confidence": 0.95,
        }

        result = self.system.ask("How many customers?")

        assert result["question"] == "How many customers?"
        assert "SELECT" in result["generated_sql"].upper()
        assert result["answer"] == "There are 5 customers."
        assert result["row_count"] == 1
        assert 0.0 <= result["confidence"] <= 1.0

    def test_ask_returns_clarification(self):
        self.mock_llm.generate_sql.return_value = {
            "type": "clarification",
            "question": "Which country?",
            "options": ["Vietnam", "USA", "Other (please specify)"],
        }

        result = self.system.ask("Show me customers")

        assert result["type"] == "clarification"
        assert result["question"] == "Which country?"
        assert len(result["options"]) == 3

    def test_ask_handles_validation_error(self):
        self.mock_llm.generate_sql.return_value = {
            "type": "sql",
            "sql": "DROP TABLE customers",
            "explanation": "Drop table",
        }

        result = self.system.ask("Delete everything")

        assert "error" in result.get("type", "") or "error" in result.get("answer", "").lower()

    def test_ask_handles_sql_execution_error(self):
        self.mock_llm.generate_sql.return_value = {
            "type": "sql",
            "sql": "SELECT * FROM nonexistent",
            "explanation": "Query nonexistent table",
        }

        result = self.system.ask("Show nonexistent")

        assert "error" in result.get("type", "") or "error" in result.get("answer", "").lower()

    def test_ask_handles_llm_error(self):
        self.mock_llm.generate_sql.return_value = {
            "type": "error",
            "message": "LLM did not call any tool.",
        }

        result = self.system.ask("???")

        assert "error" in result.get("type", "") or "error" in result.get("answer", "").lower()

    def test_confidence_reduced_for_empty_result(self):
        self.mock_llm.generate_sql.return_value = {
            "type": "sql",
            "sql": "SELECT * FROM customers WHERE country = 'Antarctica'",
            "explanation": "Find Antarctica customers",
        }
        self.mock_llm.interpret_result.return_value = {
            "answer": "No customers found.",
            "confidence": 0.9,
        }

        result = self.system.ask("Customers in Antarctica?")

        assert result["row_count"] == 0
        assert result["confidence"] < 0.9  # reduced by heuristic


class TestNLToSQLSystemIntegration:
    """Integration tests with real DB, mock LLM, real validator."""

    def setup_method(self):
        self.db = DatabaseManager(":memory:")
        self.db.init_db()
        self.mock_llm = MagicMock()
        self.system = NLToSQLSystem(
            llm=self.mock_llm,
            validator=validate_and_enforce,
            db=self.db,
        )

    def test_full_flow_aggregation(self):
        self.mock_llm.generate_sql.return_value = {
            "type": "sql",
            "sql": "SELECT country, COUNT(*) as cnt FROM customers GROUP BY country",
            "explanation": "Count customers by country",
        }
        self.mock_llm.interpret_result.return_value = {
            "answer": "Vietnam has 2 customers, USA has 1, Japan has 1, Spain has 1.",
            "confidence": 0.95,
        }

        result = self.system.ask("How many customers per country?")

        assert result["type"] == "answer"
        assert result["row_count"] == 4
        assert result["confidence"] > 0.9

        # Verify interpret_result was called with correct data
        call_args = self.mock_llm.interpret_result.call_args
        columns = call_args[1]["columns"] if "columns" in call_args[1] else call_args[0][2]
        assert "country" in columns

    def test_full_flow_join(self):
        self.mock_llm.generate_sql.return_value = {
            "type": "sql",
            "sql": "SELECT c.name, o.product_name, o.amount FROM customers c JOIN orders o ON c.id = o.customer_id WHERE c.country = 'Vietnam'",
            "explanation": "Vietnam customers with orders",
        }
        self.mock_llm.interpret_result.return_value = {
            "answer": "Vietnamese customers ordered Laptop, Mouse, Phone, and Case.",
            "confidence": 0.9,
        }

        result = self.system.ask("What did Vietnamese customers order?")

        assert result["type"] == "answer"
        assert result["row_count"] == 4

    def test_full_flow_empty_result(self):
        self.mock_llm.generate_sql.return_value = {
            "type": "sql",
            "sql": "SELECT * FROM customers WHERE country = 'Antarctica'",
            "explanation": "Find customers in Antarctica",
        }
        self.mock_llm.interpret_result.return_value = {
            "answer": "No customers found in Antarctica.",
            "confidence": 0.8,
        }

        result = self.system.ask("Customers in Antarctica?")

        assert result["type"] == "answer"
        assert result["row_count"] == 0
        assert result["confidence"] < 0.8  # heuristic reduces it
