class NLToSQLSystem:
    def __init__(self, llm, validator, db):
        self.llm = llm
        self.validator = validator
        self.db = db

    MAX_QUESTION_LENGTH = 500

    def ask(self, question: str) -> dict:
        # Input guardrail: reject empty or excessively long questions
        question = question.strip()
        if not question:
            return self._error_response(question, "Please enter a question.")
        if len(question) > self.MAX_QUESTION_LENGTH:
            return self._error_response(
                question, f"Question too long ({len(question)} chars). Max {self.MAX_QUESTION_LENGTH}."
            )

        schema = self.db.get_schema()
        data_context = self.db.get_data_context()

        # Step 1: Generate SQL or clarification
        try:
            llm_result = self.llm.generate_sql(question, schema, data_context)
        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg or "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
                return self._error_response(question, "Invalid or missing API key. Please check your API key in the Config tab.")
            if "404" in error_msg or "not found" in error_msg.lower():
                return self._error_response(question, "Model not found. Please check the model name in the Config tab.")
            if "429" in error_msg or "rate limit" in error_msg.lower():
                return self._error_response(question, "Rate limit exceeded. Please wait a moment and try again.")
            if "connection" in error_msg.lower() or "connect" in error_msg.lower():
                return self._error_response(question, "Cannot connect to LLM server. Please check the Base URL in the Config tab.")
            return self._error_response(question, f"LLM error: {e}")

        # Step 2: Handle clarification
        if llm_result["type"] == "clarification":
            return {
                "type": "clarification",
                "question": llm_result["question"],
                "options": llm_result["options"],
            }

        # Step 3: Handle LLM error
        if llm_result["type"] == "error":
            return self._error_response(question, llm_result["message"])

        # Step 4: Validate SQL
        raw_sql = llm_result["sql"]
        try:
            safe_sql = self.validator(raw_sql)
        except ValueError as e:
            return self._error_response(question, f"SQL validation error: {e}")

        # Step 5: Execute SQL
        try:
            columns, rows = self.db.execute(safe_sql)
        except Exception as e:
            return self._error_response(question, f"SQL execution error: {e}")

        # Step 6: Interpret result
        try:
            interpretation = self.llm.interpret_result(question, safe_sql, columns, rows)
        except Exception as e:
            return self._error_response(
                question,
                f"Could not interpret results: {e}",
                generated_sql=safe_sql,
                row_count=len(rows),
            )

        # Step 7: Calculate confidence
        confidence = self._calculate_confidence(
            interpretation.get("confidence", 0.5), rows
        )

        return {
            "type": "answer",
            "question": question,
            "generated_sql": safe_sql,
            "explanation": llm_result.get("explanation", ""),
            "answer": interpretation["answer"],
            "row_count": len(rows),
            "confidence": confidence,
            "system_prompt": llm_result.get("system_prompt", ""),
        }

    def _calculate_confidence(self, llm_confidence: float, rows: list) -> float:
        confidence = llm_confidence
        if len(rows) == 0:
            confidence *= 0.8
        elif len(rows) > 50:
            confidence *= 0.9
        return max(0.0, min(1.0, confidence))

    def _error_response(
        self, question: str, message: str, generated_sql: str = "", row_count: int = 0
    ) -> dict:
        return {
            "type": "error",
            "question": question,
            "generated_sql": generated_sql,
            "answer": f"Error: {message}",
            "row_count": row_count,
            "confidence": 0.0,
        }
