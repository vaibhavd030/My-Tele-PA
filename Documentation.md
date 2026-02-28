# My Tele PA: Detailed Technical Documentation

This document provides an in-depth, technical breakdown of the My Tele PA architecture, libraries, file structure, and core component interactions. This acts as the primary source of truth for maintainers and developers.

---

## 1. Core Technology Stack

The project sits at the intersection of Agentic AI, robust Data Engineering, and asynchronous application development. 

### Key Dependencies
- **LangGraph** (`langgraph`): The backbone of the agent. Allows building cyclical graphs (state machines) where each node is a python function or LLM call. Crucial for handling multi-turn conversational memory (using `MemorySaver`) without looping endlessly.
- **Instructor** (`instructor`): Exerts strict JSON schema constraints on the OpenAI API. It intercepts the LLM output and forces it to map perfectly to predefined Pydantic models.
- **Pydantic v2** (`pydantic`): Strongly typed schemas. Used everywhere—from validating environmental variables (`BaseSettings`) to enforcing that sleep duration is an integer > 0 but < 24.
- **SQLite & Aiosqlite** (`aiosqlite`): The local, lightning-fast relational database. It stores historical logs for the Query Node to aggregate, and also powers LangGraph's conversational memory persistence.
- **Python Telegram Bot** (`python-telegram-bot`): Fully asynchronous framework connecting the LangGraph application to the end-user via Telegram. Provides the webhooks, polling loops, and chat interfaces.
- **Notion Client** (`notion-client`): Asynchronous SDK used to append Notion database blocks and text. 
- **APScheduler** (`APScheduler`): An in-process python job scheduler. Runs the proactive chron jobs (morning check-ins and weekly digests) without needing external services like Celery or Redis.
- **Ruff & UV**: UV manages packages synchronously and insanely fast, while Ruff replaces flake8/black/isort in a single Rust-compiled binary.

---

## 2. System Architecture & Component Interaction

The Telegram layer merely forwards user messages as `raw_input` into the **LangGraph Agent State**. The graph determines exactly what happens next.

### The Agent State (`AgentState`)
Defined in `src/life_os/agent/state.py`. This is the "shared memory dictionary" that gets passed between all graph.py nodes. 
- `raw_input`: The text the user sent.
- `chat_history`: Stores past tuples of user and bot messages (critical for resolving missing fields across multiple replies).
- `intent`: Classified as `log`, `query`, or `other`.
- `entities`: Extracted Pydantic models serialized into dicts (e.g., `exercise`, `sleep`, `tasks`).
- `missing_fields`: Variables required but missing (e.g. user said "gym" but no duration).
- `response_message`: The final formatted string the bot will reply with.

### Node Flow Breakdown
1. **Guard Input (`guard.py`)**: A safety node. Scans incoming text for malicious intents, prompt injections, or extreme length (DOS protection). Aborts graph execution if triggered.
2. **Classifier (`classifier.py`)**: Uses a lightweight LLM call to categorize intent. 
   - `log`: Extracting data.
   - `query`: Asking for summaries.
   - `other`: Chitchat or greetings.
3. **Extractor (`extractor.py`)**: The heaviest node. Uses Instructor and GPT-4o. Takes the `chat_history` and `raw_input`, validates against schemas (like `ExerciseEntry`), and merges partial payloads into the AgentState. It also enforces missing-field checks (e.g., if Activity is GYM but body_part is missing, it adds "body part" to `missing_fields`).
4. **Clarification Loop (`graph.py` edge logic)**: If `missing_fields` exist, the state machine *pauses* and routes straight to Output, asking the user a question. When the user replies, the state resumes at Classifier, but `chat_history` provides context so Extractor can fill in the blank.
5. **Persister (`persister.py`)**: Reached only if no missing fields exist. Formats the confirmation message, commits records to SQLite, reconstructs Pydantic models, and asynchronously syncs arrays to Notion APIs.
6. **Query (`query.py`)**: Triggered by the `query` intent. Loads SQLite tables into Pandas dataframes, feeds the context to an LLM, and answers analytical questions ("When did I sleep the worst this week?").
7. **Chitchat (`graph.py / chitchat_node`)**: Bypasses heavy schema logic. Provides a warm, 1-2 sentence conversational fallback, gently bringing the user back to logging.

---

## 3. Directory & File Breakdown

### Root Scaffolding
- `simulation.py`: A CLI-based script that allows terminal interaction with the LangGraph agent. Extremely useful because it bypasses Telegram entirely for rapid prototyping.
- `pyproject.toml` / `uv.lock`: Modern dependency management using Astral's `uv`.
- `Makefile`: Single commands for standardizing builds (e.g. `make test`, `make dev`).
- `Dockerfile` & `fly.toml`: Configured for immediate cloud-native deployment on Fly.io, complete with SQLite volume mounting logic.

### `src/life_os/`
The core business logic. Separation of concerns is strictly enforced.

#### `config/`
- **`settings.py`**: Centralizes ENV variables via Pydantic `BaseSettings`. Handles secret unmasking safely.
- **`logging.py`**: Configures `structlog` for structured JSON console outputs. Crucial for tracing graph execution steps linearly.

#### `models/`
Strict validation schemas.
- **`wellness.py`**: Enums for `ExerciseType`, `SleepQuality`, `MuscleGroup`. Defines the `SleepEntry` and `ExerciseEntry` payloads, ensuring things like `intensity` stay between 1-10.
- **`tasks.py`**: Defines `TaskItem` (for to-dos) and `ReadingLink` (cleans trailing slashes from URLs).
- **`guardrails.py`**: Output structures for the classifiers (e.g., `IntentClassification` with valid enum literals).

#### `agent/`
- **`graph.py`**: The "Router". Binds all nodes and state together into the compiled `StateGraph`. Instantiates the `MemorySaver` checkpointer.
- **`state.py`**: Declares `AgentState(TypedDict)` structure.
- **`prompts/extract.txt`**: The massive master prompt holding numbering and edge-cases (e.g., timezone bounds, meditation definitions). Loaded directly from disk into the Extractor.
- **`nodes/*.py`**: As described in Node Flow Breakdown. Every file here takes an `AgentState` as input and returns a `dict` representing state variables to update.

#### `integrations/`
- **`sqlite_store.py`**: Bootstraps the local DB, creates tables, and houses async queries (`save_records`, `fetch_recent_records`). Uses `aiosqlite` Context Managers to prevent DB lock exceptions.
- **`notion_store.py`**: Initializes the `AsyncClient`. Maps our custom Pydantic models into the extremely specific mapping arrays required by Notion's rich-text block API natively.

#### `telegram/`
- **`bot.py`**: The main entry point bridging Telegram to LangGraph. It uses `python-telegram-bot` to constantly poll the Telegram API for new messages (`Update` objects). 
  - **Authentication**: When a message arrives, it immediately checks if the `user_id` is in the allowed whitelist. If not, it drops the message silently.
  - **Execution Bridge**: Valid messages are mapped into a `raw_input` string and fed into `app.ainvoke(state, config={"configurable": {"thread_id": user_id}})`. This executes the LangGraph state machine.
  - **Response Routing**: Once LangGraph yields a final state, `bot.py` extracts the `response_message` string and uses `context.bot.send_message` to push it back to the user's Telegram chat.
- **`jobs.py`**: The APScheduler instance housing `send_morning_checkin()` and `send_weekly_digest()`. These run on cron schedules and push standalone messages to the user entirely independent of graph execution.

#### `evals/`
- **`run_evals.py` & `metrics.py`**: A custom pipeline. Feeds `.jsonl` conversational mock messages into the Extractor, calculates exact precision/recall using F1 scoring on dictionary keys mapping. Ensures PRs don't break existing extraction accuracy. 

---

## 4. Safety & Security Checks

- **Authentication Enforcement**: Inside `telegram/bot.py`, an incoming `user_id` is matched against an environment list of allowed users. Unauthorized users receive a silent abort response.
- **Input Guardrails**: `guard_input` node runs a deterministic LLM layer explicitly instructed to detect code injections or attempts to alter prompt behavior (e.g., "Ignore previous instructions").
- **API Retries**: The Notion integration heavily utilizes `Tenacity`. If the Notion API rate limits or drops a packet, the script linearly backoffs and retries 3 times before failing gracefully.
- **DB Checkpointing**: LangGraph’s checkpointing uses serialized msgpack data. By forcing Pydantic models back to primitive JSON dicts inside the `extractor`, we ensure state data never corrupts during Thread saving.

## 5. Interactions via MCP (Model Context Protocol)

Currently, the primary external integrations are **SQLite** and **Notion APIs** operating directly within standard custom python wrappers as LangGraph Nodes (`query.py` and `persister.py`). 

There are currently no external MCP servers instantiated in the repository. The LangGraph generic agent architecture allows for instantaneous plugging of MCP servers by dropping them in as `ToolNodes` on the `graph.py` pipeline if required in the future, but the current production flow relies natively on direct SDK connections.
