import os
import sqlglot
import streamlit as st
from dotenv import load_dotenv
from core.database import DatabaseManager
from core.llm_client import LLMClient
from core.sql_validator import validate_and_enforce
from core.system import NLToSQLSystem

load_dotenv()


def get_llm_config() -> dict:
    """Get LLM config from session state, falling back to env vars."""
    return {
        "api_key": st.session_state.get("api_key", os.getenv("OPENAI_API_KEY", "")),
        "base_url": st.session_state.get("base_url", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")),
        "model": st.session_state.get("model", os.getenv("OPENAI_MODEL", "gpt-4o")),
    }


def init_system() -> NLToSQLSystem:
    db = DatabaseManager(":memory:")
    db.init_db()
    config = get_llm_config()
    llm = LLMClient(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
    )
    return NLToSQLSystem(llm=llm, validator=validate_and_enforce, db=db)


def get_system() -> NLToSQLSystem:
    if "system" not in st.session_state:
        st.session_state.system = init_system()
    return st.session_state.system


def format_sql(sql: str) -> str:
    try:
        return sqlglot.transpile(sql, pretty=True)[0]
    except Exception:
        return sql


def render_sidebar():
    with st.sidebar:
        st.header("NL-to-SQL Assistant")
        st.caption("Ask questions about your database in natural language.")

        st.button("Reset conversation", on_click=reset_conversation, use_container_width=True)

        for category, questions in SAMPLE_QUESTIONS.items():
            with st.expander(category):
                for j, q in enumerate(questions):
                    if st.button(q, key=f"sidebar_sample_{category}_{j}", use_container_width=True):
                        st.session_state.sample_question = q
                        st.rerun()


def reset_conversation():
    st.session_state.messages = []
    st.session_state.pending_clarification = None


SAMPLE_QUESTIONS = {
    ":green[Easy]": [
        "How many customers are there?",
        "Show all orders placed in 2025",
    ],
    ":blue[Medium]": [
        "What is the average order amount per product?",
        "Total revenue by month",
    ],
    ":orange[Hard (JOIN)]": [
        "Which customer spent the most money in total?",
        "What is the average spending per customer by country?",
    ],
    ":red[Ambiguous]": [
        "What sells best?",
        "Who is the best customer?",
    ],
}


def render_chat_tab():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_clarification" not in st.session_state:
        st.session_state.pending_clarification = None

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant" and "result" in msg:
                render_assistant_message(msg["result"])
            else:
                st.markdown(msg["content"])

    # Handle clarification answer from previous rerun
    if st.session_state.get("clarification_answer"):
        answer = st.session_state.clarification_answer
        original = st.session_state.get("clarification_original", "")
        st.session_state.clarification_answer = None
        st.session_state.clarification_original = None
        if original:
            combined = f"{original} (clarification: {answer})"
        else:
            combined = answer
        handle_user_question(combined)
        return

    # Handle pending clarification
    if st.session_state.pending_clarification:
        render_clarification(st.session_state.pending_clarification)
        return

    # Handle sample question click
    if st.session_state.get("sample_question"):
        question = st.session_state.sample_question
        st.session_state.sample_question = None
        handle_user_question(question)
        return

    # Chat input
    if prompt := st.chat_input("Ask a question about the database..."):
        handle_user_question(prompt)


def handle_user_question(question: str):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    system = get_system()
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            result = system.ask(question)

        if result.get("type") == "clarification":
            result["original_question"] = question
            st.session_state.pending_clarification = result
            st.session_state.messages.append({
                "role": "assistant",
                "content": result["question"],
                "result": result,
            })
            st.rerun()
        else:
            st.session_state.messages.append({
                "role": "assistant",
                "content": result.get("answer", ""),
                "result": result,
            })
            st.rerun()


def escape_markdown(text: str) -> str:
    """Escape $ signs so Streamlit doesn't render them as LaTeX."""
    return text.replace("$", "\\$")


def render_assistant_message(result: dict):
    result_type = result.get("type", "")

    if result_type == "clarification":
        st.markdown(f"**{result['question']}**")
        return

    if result_type == "error":
        st.error(result.get("answer", "An error occurred."))
        return

    # Normal answer
    st.markdown(escape_markdown(result.get("answer", "")))

    if result.get("generated_sql"):
        with st.expander("Generated SQL"):
            st.code(format_sql(result["generated_sql"]), language="sql")

    if result.get("explanation"):
        with st.expander("Explanation"):
            st.markdown(result["explanation"])

    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"Rows: {result.get('row_count', 0)}")
    with col2:
        confidence = result.get("confidence", 0)
        st.caption(f"Confidence: {confidence:.0%}")


def render_clarification(clarification: dict):
    st.info(f"**{clarification['question']}**")
    options = clarification.get("options", [])
    original = clarification.get("original_question", "")

    for i, option in enumerate(options):
        if option == "Other (please specify)":
            other_input = st.text_input("Your answer:", key="clarification_other")
            if st.button("Submit", key="clarification_submit_other"):
                if other_input.strip():
                    st.session_state.pending_clarification = None
                    st.session_state.clarification_answer = other_input.strip()
                    st.session_state.clarification_original = original
                    st.rerun()
        else:
            if st.button(option, key=f"clarification_{i}"):
                st.session_state.pending_clarification = None
                st.session_state.clarification_answer = option
                st.session_state.clarification_original = original
                st.rerun()


def render_database_tab():
    system = get_system()
    data = system.db.get_tables_data()
    for table_name, table_data in data.items():
        st.subheader(f"Table: {table_name}")
        if table_data["rows"]:
            import pandas as pd
            df = pd.DataFrame(table_data["rows"], columns=table_data["columns"])
            st.dataframe(df, width="stretch")
        else:
            st.info("No data.")


def render_bonus_tab():
    st.subheader("Bonus Questions & Answers")

    with st.expander("1. How to reduce hallucinated columns?", expanded=True):
        st.markdown("""
**This system uses multiple layers to prevent column hallucination:**

- **Dynamic schema injection:** The system prompt includes the exact schema read from SQLite metadata (`PRAGMA table_info`), not a hardcoded string. The LLM only sees columns that actually exist.
- **Strict prompt instructions:** The system prompt explicitly states: *"ONLY use tables and columns listed in the schema above. If a column does not appear in the schema, it DOES NOT EXIST."*
- **Few-shot examples:** The prompt includes correct SQL examples that demonstrate proper column usage, anchoring the LLM's behavior.
- **SQL validation layer:** Even if the LLM hallucinates, `sqlglot` parses the SQL into an AST. The query will fail at execution time if it references non-existent columns, and the error is caught gracefully.
- **`temperature=0`:** Reduces randomness, making the model more likely to stick to the provided schema.
""")

    with st.expander("2. Should we use temperature=0? Why?"):
        st.markdown("""
**Yes, `temperature=0` is the right choice for this system.**

- **Determinism:** The same question should produce the same SQL every time. SQL generation is not a creative task — there is usually one correct query for a given question.
- **Reduced hallucination:** Higher temperature increases randomness, which means the model is more likely to invent column names or produce syntactically creative but incorrect SQL.
- **Reproducibility:** For debugging and evaluation, deterministic output is essential. If a query fails, you can reproduce and fix it reliably.

**When NOT to use temperature=0:**
- The `interpret_result` step could arguably use a slightly higher temperature (e.g., 0.3) for more natural-sounding answers, but we keep it at 0 for consistency.
""")

    with st.expander("3. How to evaluate this system?"):
        st.markdown("""
**Multi-level evaluation approach:**

**Level 1 — SQL Correctness (automated):**
- Build a test set of (question, expected_sql, expected_result) triples
- Compare generated SQL output against expected results (not exact SQL match, since multiple valid SQL queries can produce the same result)
- Metrics: execution accuracy, result-set match rate

**Level 2 — Answer Quality (semi-automated):**
- Compare `interpret_result` output against reference answers using LLM-as-judge (e.g., ask GPT-4 to rate correctness 1-5)
- Check for factual consistency: does the answer match the actual query results?

**Level 3 — Safety & Guardrails (automated):**
- Adversarial test set: SQL injection attempts, DML/DDL requests, nonsensical questions
- Verify: all blocked, no crashes, appropriate error messages

**Level 4 — User Satisfaction (manual):**
- A/B testing with real users
- Track: clarification rate, retry rate, task completion rate
""")

    with st.expander("4. What happens at large scale?"):
        st.markdown("""
**Several challenges emerge at scale:**

**Schema complexity:**
- Hundreds of tables with thousands of columns — the schema may exceed the LLM's context window.
- **Solution:** Schema filtering — use the question to retrieve only relevant tables/columns (e.g., via embedding similarity or keyword matching) before injecting into the prompt.

**Query performance:**
- Complex queries on large tables can be slow or time out.
- **Solution:** Query timeout limits, `EXPLAIN` analysis before execution, read replicas, query result caching.

**LLM latency & cost:**
- Each question requires 2 LLM calls (generate + interpret). At high QPS, this becomes expensive.
- **Solution:** Response caching for common questions, smaller/fine-tuned models for simple queries, batching.

**Concurrency:**
- Multiple users querying simultaneously.
- **Solution:** Connection pooling, async execution, rate limiting per user.

**Security:**
- More users = more attack surface.
- **Solution:** Per-user query quotas, audit logging, row-level security.
""")

    with st.expander("5. Dynamic schema injection — how is it designed?"):
        st.markdown("""
**This system already supports dynamic schema injection.**

**Current implementation:**
```python
# DatabaseManager.get_schema() reads directly from SQLite metadata
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
for table in tables:
    cursor.execute(f"PRAGMA table_info({table})")
```

**Why this matters:**
- Schema is **never hardcoded** in the prompt template — it's read at runtime from the actual database.
- If you add a new table or column to the database, the next question will automatically include the updated schema.
- The `SYSTEM_PROMPT_TEMPLATE` uses `{schema}` placeholder, filled dynamically per request.

**To extend for multiple databases:**
- Accept a `db_path` or connection string parameter
- `DatabaseManager` connects to the target database
- `get_schema()` reads that database's metadata
- Everything else (validation, LLM, UI) works unchanged
""")


def render_flow_tab():
    st.subheader("System Flow")

    st.graphviz_chart("""
    digraph {
        rankdir=TB
        node [shape=box style="rounded,filled" fontname="Helvetica" fontsize=12 margin="0.3,0.15"]
        edge [fontname="Helvetica" fontsize=10]

        A [label="User asks a question" fillcolor="#E3F2FD"]

        B [label="1. LLMClient.generate_sql()\\nLLM receives schema + question" fillcolor="#BBDEFB"]

        C [label="Which tool\\ndoes LLM call?" shape=diamond fillcolor="#FFF9C4"]

        D [label="2. SQL Validation\\nsqlglot AST parse\\nSELECT only | Block DML | Enforce LIMIT" fillcolor="#C8E6C9"]

        E [label="Display clarification\\nquestion + options\\nUser selects an answer" fillcolor="#FFE0B2"]

        F [label="3. SQL Execution\\nSQLite runs query\\nReturns (columns, rows)" fillcolor="#C8E6C9"]

        G [label="Return error message" fillcolor="#FFCDD2"]

        H [label="4. LLMClient.interpret_result()\\nLLM interprets results\\nReturns answer + confidence" fillcolor="#BBDEFB"]

        I [label="5. Confidence Heuristic\\nEmpty result: x0.8\\nLarge result >50: x0.9" fillcolor="#D1C4E9"]

        J [label="6. Return result\\n{question, generated_sql,\\nanswer, row_count, confidence}" fillcolor="#B2DFDB"]

        A -> B
        B -> C
        C -> D [label="execute_sql"]
        C -> E [label="ask_clarification"]
        E -> A [label="user choice +\\noriginal question"]
        D -> F [label="valid"]
        D -> G [label="invalid"]
        F -> H
        F -> G [label="SQL error" style=dashed]
        H -> I
        I -> J
    }
    """)



def render_config_tab():
    st.subheader("OpenAI Compatible API Configuration")

    config = get_llm_config()

    base_url = st.text_input(
        "Base URL",
        value=config["base_url"],
        placeholder="https://api.openai.com/v1",
    )
    api_key = st.text_input(
        "API Key",
        value=config["api_key"],
        type="password",
        placeholder="sk-...",
    )
    model = st.text_input(
        "Model",
        value=config["model"],
        placeholder="gpt-4o",
    )

    if st.button("Save & Reconnect", use_container_width=True):
        if not api_key.strip():
            st.error("API Key is required.")
        elif not base_url.strip():
            st.error("Base URL is required.")
        elif not model.strip():
            st.error("Model name is required.")
        else:
            st.session_state.api_key = api_key.strip()
            st.session_state.base_url = base_url.strip()
            st.session_state.model = model.strip()
            # Force re-init system with new config
            st.session_state.pop("system", None)
            st.success(f"Connected to **{model}** at `{base_url}`")

    st.divider()
    st.caption("Configuration priority: this tab > .env file > defaults")


def main():
    st.set_page_config(page_title="NL-to-SQL", page_icon="🔍", layout="wide")
    render_sidebar()

    tab_chat, tab_db, tab_flow, tab_config, tab_bonus = st.tabs(
        ["Chat", "Database", "System Flow", "Config", "Design Notes"]
    )

    with tab_chat:
        render_chat_tab()

    with tab_db:
        render_database_tab()

    with tab_flow:
        render_flow_tab()

    with tab_config:
        render_config_tab()

    with tab_bonus:
        render_bonus_tab()


if __name__ == "__main__":
    main()
