# NL-to-SQL Mini System

A system that converts natural language questions into SQL queries, executes them against a database, and returns human-readable answers.

## Tech Stack

- **Python 3.11+**
- **Streamlit** — chat interface
- **OpenAI SDK** — LLM calls (compatible with any OpenAI-compatible API)
- **SQLite** — lightweight in-memory database
- **sqlglot** — SQL parsing and validation via AST

## Setup & Run

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env: fill in OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
streamlit run app.py
```

## Architecture

```
app.py                  → Streamlit UI (Chat tab + Database tab)
core/
  system.py             → NLToSQLSystem — orchestrator coordinating the full pipeline
  llm_client.py         → LLMClient — OpenAI SDK with tool calling
  sql_validator.py      → validate_and_enforce() — SQL safety checks via sqlglot AST
  database.py           → DatabaseManager — SQLite connection + mock data
```

## Main Flow

```
User asks: "What did Vietnamese customers order?"
        │
        ▼
┌──────────────────────────────────────────────────────┐
│  1. LLMClient.generate_sql(question, schema)         │
│     LLM receives database schema + user question     │
│     LLM decides which tool to call:                  │
│       • execute_sql → generates SQL query             │
│       • ask_clarification → asks user to clarify      │
└──────────┬───────────────────────┬───────────────────┘
           │                       │
     [execute_sql]          [ask_clarification]
           │                       │
           ▼                       ▼
┌─────────────────────┐  ┌────────────────────────────┐
│  2. SQL Validation   │  │  Display question + options │
│  sqlglot AST parse   │  │  User selects → back to (1) │
│  • SELECT only       │  └────────────────────────────┘
│  • Block DML/DDL     │
│  • Enforce LIMIT     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  3. SQL Execution    │
│  SQLite runs query   │
│  → (columns, rows)   │
└──────────┬──────────┘
           │
           ▼
┌──────────────────────────────────────────────────────┐
│  4. LLMClient.interpret_result(question, sql, rows)  │
│     LLM interprets results into natural language     │
│     + returns confidence score (0.0 - 1.0)           │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────┐
│  5. Confidence Heuristic                              │
│     Combines LLM confidence + adjustments:           │
│     • Empty result → ×0.8                             │
│     • >50 rows → ×0.9                                 │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────┐
│  6. Return result                                     │
│  {question, generated_sql, answer, row_count,         │
│   confidence}                                         │
└──────────────────────────────────────────────────────┘
```

## SQL Validation

Uses **sqlglot** to parse SQL into an AST (Abstract Syntax Tree) and enforce safety rules:

| Rule | Description |
|------|-------------|
| Non-empty | Reject empty queries |
| Parseable | Reject syntax errors |
| Single statement | Prevent injection via `SELECT 1; DROP TABLE` |
| SELECT only | Block all DML/DDL (INSERT, UPDATE, DELETE, DROP, CREATE, ALTER) |
| Enforce LIMIT | Auto-add `LIMIT 100` if missing, cap if exceeding max |

## Prompt Design

**System prompt for SQL generation:**
- Database schema dynamically injected (read from SQLite metadata)
- Only allows tables/columns present in the schema
- Prohibits DML/DDL generation
- Requires clear aliases when using JOIN
- `temperature=0` for deterministic output

**Tool calling:**
- `execute_sql(sql, explanation)` — LLM generates SQL when the question is clear
- `ask_clarification(question, options)` — LLM asks for clarification when the question is ambiguous, with 2-4 suggested options + "Other"

## Sample Database

**customers** (5 rows): customers from Vietnam, USA, Japan, Spain

**orders** (10 rows): orders for products including Laptop, Mouse, Keyboard, Monitor, Headphones, Phone, Case, Tablet

Covers: JOIN, aggregation (SUM/COUNT/AVG), filter (country/date), GROUP BY.

## Running Tests

```bash
pytest tests/ -v
```

34 tests including:
- Unit tests for DatabaseManager, SQLValidator, NLToSQLSystem
- Integration tests for the full flow (real DB + real validator + mock LLM)
