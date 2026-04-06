import json
from openai import OpenAI


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": "Generate a SQL SELECT query to answer the user's question. Only use tables and columns from the provided schema.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "A valid SQL SELECT query"
                    },
                    "explanation": {
                        "type": "string",
                        "description": "Brief explanation of what this query does"
                    }
                },
                "required": ["sql", "explanation"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": "Ask the user to clarify their question when it is ambiguous. Provide 2-4 suggested options plus an 'Other' option.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The clarification question to ask the user"
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2-4 suggested answers. The last option must always be 'Other (please specify)'"
                    }
                },
                "required": ["question", "options"]
            }
        }
    }
]

# TODO: Add relationship descriptions (FK mappings) to schema injection dynamically
# from DB metadata, so LLM can infer JOINs without hardcoding.
SYSTEM_PROMPT_TEMPLATE = """You are a precise SQL assistant for a SQLite database. Your ONLY job is to convert natural language questions into correct, safe SQL queries.

## Database Schema (ONLY these tables and columns exist)
{schema}

## Data Context (actual values in the database)
{data_context}

## Strict Rules
1. **Schema adherence:** ONLY use tables and columns listed above. If a column does not appear in the schema, it DOES NOT EXIST. Never guess or invent column names.
2. **SELECT only:** NEVER generate DROP, DELETE, UPDATE, INSERT, CREATE, ALTER, or any data-modifying statement.
3. **SQLite dialect:** Use SQLite-compatible syntax. Key differences:
   - Dates are stored as TEXT in 'YYYY-MM-DD' format. Use string comparison or `date()` function for filtering.
   - Use `||` for string concatenation (not CONCAT).
   - No ILIKE — use `LOWER(column) LIKE LOWER(pattern)` for case-insensitive matching.
4. **JOINs:** Always use explicit JOIN with clear table aliases (e.g., `customers AS c JOIN orders AS o ON c.id = o.customer_id`). Never use implicit comma joins.
5. **No SELECT *:** Always list specific column names instead of `SELECT *`. This makes queries more readable and avoids returning unnecessary data.
6. **Aggregations:** When using aggregate functions (COUNT, SUM, AVG, etc.), always include appropriate GROUP BY clause. Use meaningful aliases for computed columns (e.g., `COUNT(*) AS total_orders`).
7. **NULL handling:** Use `IS NULL` / `IS NOT NULL`, never `= NULL`.
8. **Ranking/Top-N:** When the user asks for "top", "best", "most", "highest", or "lowest", always use ORDER BY + LIMIT. Example: "top 3 customers" → ORDER BY ... DESC LIMIT 3.
9. **Ambiguity:** If the user's question is vague, references unknown entities, or could be interpreted multiple ways, call `ask_clarification` instead of guessing. It is better to ask than to return wrong results.
10. **Always call a tool.** Never respond with plain text.

## Examples

Question: "How many customers are from Vietnam?"
Tool: execute_sql
SQL: SELECT COUNT(*) AS customer_count FROM customers WHERE country = 'Vietnam'
Explanation: Count customers filtered by country = Vietnam

Question: "Show me the total spending per customer"
Tool: execute_sql
SQL: SELECT c.name, SUM(o.amount) AS total_spent FROM customers AS c JOIN orders AS o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY total_spent DESC
Explanation: Join customers with orders, sum amount grouped by customer, ordered by highest spender

Question: "Show me the data"
Tool: ask_clarification
Question: "Which data would you like to see?"
Options: ["All customers", "All orders", "Customer order summary", "Other (please specify)"]

Question: "Which customer bought the most?"
WRONG: SELECT customer_id, COUNT(*) FROM orders GROUP BY customer_id ORDER BY COUNT(*) DESC LIMIT 1
(Missing customer name — always JOIN to get human-readable data)
CORRECT: SELECT c.name, COUNT(*) AS order_count FROM customers AS c JOIN orders AS o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY order_count DESC LIMIT 1
Explanation: Join to get customer name, count orders, return top 1
"""

INTERPRET_PROMPT_TEMPLATE = """You are a data analyst presenting query results to a non-technical user.

## Context
User asked: "{question}"
SQL executed: {sql}
Result columns: {columns}
Result rows ({row_count} total):
{rows}

## Instructions
1. **Be concise.** Answer in 1-2 sentences max. No filler, no preamble, no "Based on the query results...".
2. **Be specific.** Include actual numbers, names, and dates. Round currency to 2 decimal places.
3. **Empty results:** State clearly that no data was found, in one sentence.
4. **Large results:** Summarize key insights (top/bottom, totals) — do not list every row.
5. **No raw SQL.** Never include SQL syntax in your answer.
6. **Confidence score:** Rate how well the SQL query matches the user's intent:
   - 0.9-1.0: Query directly and precisely answers the question
   - 0.7-0.8: Query answers the question but might miss nuance
   - 0.5-0.6: Query partially answers, interpretation needed
   - Below 0.5: Query may not correctly address the question

Respond in JSON: {{"answer": "your natural language answer", "confidence": 0.0-1.0}}
"""


class LLMClient:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    # TODO: Add retry logic — if SQL validation/execution fails, feed the error
    # back to the LLM and ask it to regenerate (max 2-3 retries).
    def generate_sql(self, question: str, schema: str, data_context: str = "") -> dict:
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema=schema, data_context=data_context or "No additional context available.")

        # Determinism: temperature=0 ensures the same question produces the same SQL
        # every time, which is critical for reproducibility, debugging, and evaluation.
        # tool_choice="required" forces the model to always call a tool (execute_sql or
        # ask_clarification) rather than responding with free-form text.
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            tools=TOOL_DEFINITIONS,
            tool_choice="required",
        )

        message = response.choices[0].message

        if not message.tool_calls:
            return {"type": "error", "message": "LLM did not call any tool.", "system_prompt": system_prompt}

        tool_call = message.tool_calls[0]
        args = json.loads(tool_call.function.arguments)

        if tool_call.function.name == "execute_sql":
            return {
                "type": "sql",
                "sql": args["sql"],
                "explanation": args.get("explanation", ""),
                "system_prompt": system_prompt,
            }
        elif tool_call.function.name == "ask_clarification":
            options = args.get("options", [])
            if not options or options[-1] != "Other (please specify)":
                options.append("Other (please specify)")
            return {
                "type": "clarification",
                "question": args["question"],
                "options": options,
                "system_prompt": system_prompt,
            }

        return {"type": "error", "message": f"Unknown tool: {tool_call.function.name}"}

    def interpret_result(
        self, question: str, sql: str, columns: list[str], rows: list[tuple]
    ) -> dict:
        rows_str = "\n".join(str(row) for row in rows) if rows else "(no results)"
        columns_str = ", ".join(columns)

        prompt = INTERPRET_PROMPT_TEMPLATE.format(
            question=question, sql=sql, columns=columns_str,
            rows=rows_str, row_count=len(rows)
        )

        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.choices[0].message.content.strip()

        try:
            data = json.loads(text)
            return {
                "answer": data.get("answer", text),
                "confidence": float(data.get("confidence", 0.5)),
                "interpret_prompt": prompt,
            }
        except (json.JSONDecodeError, ValueError):
            return {"answer": text, "confidence": 0.5, "interpret_prompt": prompt}
