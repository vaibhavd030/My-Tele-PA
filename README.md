# My Tele PA (Personal Life OS Agent v2.0)

A production-grade Telegram bot agent that acts as a Personal Life OS. It tracks wellness (sleep, exercise, mood), tasks, reading links, and journal entries using **LangGraph**, **Instructor**, and **GPT-4o**. 

The system leverages conversational memory to naturally clarify missing information, rigidly validates extracted payloads using **Pydantic**, stores data centrally using **Google BigQuery**, and conditionally syncs all organized data straight to **Notion databases**.

## ✨ Features

- **Voice Note Parsing**: Send audio or voice notes; the bot transcribes them instantly using OpenAI Whisper and merges the context smoothly into your journal.
- **Contextual NLP Parsing**: Handles natural conversational language to log complex life entities at once.
- **Auto-Routing (Notion Sync)**: Pushes Reading Links, Tasks, Journal Entries, Exercise, specific Spiritual Practices (Sitting, Cleaning, Meditation), Habit Tracking, and Sleep straight to designated Notion databases seamlessly.
- **Unified Journaling (Mood & Energy)**: Subjective feelings and metrics (like Mood and Energy levels) are extracted and safely prepended to your rich-text journal entries to ensure the emotional narrative is never lost (e.g., `[Mood: 8/10] | [Energy: 7/10] I felt really productive today...`).
- **Natural Language Analytics (BigQuery)**: You can query your historical data naturally. E.g., *"How much did I sleep in the last 2 days?"* or *"What was my average mood this week?"* The agent translates this to active BigQuery Standard SQL, parses the results, and replies conversationally.
- **Interactive Clarification Loop**: If you provide partial data (e.g., "Went to the gym"), the agent pauses and asks for the missing fields (e.g., "Which body part did you train?").
- **Apple Health Integration SDK**: Built-in webhook for the 'Health Auto Export' iOS app to passively ingest Apple Health Sleep records into your Life OS.
- **Proactive Schedulers**: Automatically pings you at 8am daily for check-ins and Sunday at 7pm for a weekly digest.
- **Serverless Ready (Cloud Run)**: Fully compatible with Google Cloud Run using an optimized synchronous webhook design that scales to zero to save costs. Stateful checkpoints are preserved via mounted volumes.

---

## 🏗️ Architecture

The system runs as an asynchronous Telegram polling/webhook application paired with a robust Agentic Workflow:

- **LangGraph**: Orchestrates the state machine, routing between classification, entity extraction, missing-field logic loops, analytical querying, and database persistence.
- **Instructor**: Enforces deterministic JSON schemas directly from the OpenAI `gpt-4o` models.
- **Pydantic (v2)**: Validates typing and value thresholds across all extracted payloads.
- **Google BigQuery**: Provides high-speed serverless querying capability mapped naturally to Google Connected Sheets.
- **SQLite**: Handles `AsyncSqliteSaver` agent conversational memory checkpoints across serverless webhooks.

### Agentic Graph Flow

```mermaid
graph TD
    User([Telegram User]) -->|Message| Bot[Telegram Bot]
    Bot --> Graph[LangGraph Agent]
    
    subgraph Agent Workflow
        Graph --> GuardInput[Guard Input]
        GuardInput --> Classify[Classifier Node]
        
        Classify -- "Intent: Log" --> Extract[Extractor Node]
        Classify -- "Intent: Query" --> Query[Query Node]
        Classify -- "Intent: Other" --> Chitchat[Chitchat Node]
        
        Extract --> CheckMissing{Missing Fields?}
        CheckMissing -- "Yes" --> GuardOutput
        CheckMissing -- "No" --> Persist[Persister Node]
        
        Persist --> Storage[(Google BigQuery)]
        Persist -.-> Notion[Notion API]
        
        Query --> Storage
        Query --> GuardOutput
        Chitchat --> GuardOutput
        Persist --> GuardOutput
    end
    
    GuardOutput --> Bot
```

---

## 🗺️ Core Modules & Usage Roadmap

The Life OS agent is designed to be your central hub for tracking personal metrics. Below is a roadmap of the core modules, their scope, and how to use them natively via Telegram.

### 1. 📝 Journaling & Subjective Moods
**Scope**: Capturing your daily narrative, thoughts, and subjective feelings.
**How it Works**: The agent actively extracts your text narrative while looking for subjective markers (e.g., "I feel happy" or "I'm exhausted"). It prepends a validated `[Mood: X/10] | [Energy: Y/10]` score directly to your text so the emotional context is never lost in Notion.

**User:** 
> "I feel pretty sad about the job rejection today, my energy is completely gone."

**Bot:**
> I have logged the following:
> 📝 Journal: [Mood: 3/10] | [Energy: 2/10] I feel pretty sad about the job rejection today, my energy is completely gone.
> ✨ Synced to Notion!

### 2. 🧘 Spiritual Practices & Meditation
**Scope**: Tracking mindfulness sessions, specifically supporting general `Meditation`, Heartfulness `Cleaning`, `Sitting` (Transmission), and `Group Meditation` (Satsang).
**How it Works**: Just dictate what you did and for how long. The agent maps it to the specific spiritual practice schema. For 'Sittings', you can mention the preceptor, and for 'Group Meditations', you can mention the location.

**User:** 
> "Did 45 mins of cleaning at 6pm, and then a 30 min sitting from John."

**Bot:**
> I have logged the following:
> 🧘 Wellness: @ 18:00, 45 mins (Cleaning) | @ 18:45, 30 mins (Sitting from John)
> ✨ Synced to Notion!

### 3. 🏃 Exercise & Training Logging
**Scope**: Logging physical activity including run, walk, gym/weights, yoga, swim, cycle, and other custom physical activities.
**How it Works**: If you mention weight training, the Pydantic schema expects to know the *Duration* and the *Muscle Group* (Chest, Biceps, Full Body, etc.). If you forget a required field, the Clarification Loop will simply ask you for it!

**User:** 
> "Went to the gym for 45 mins and did a heavy chest and triceps day. Intensity was an 8."

**Bot:**
> I have logged the following:
> 🏃 Exercise: Gym, 45 mins | Body: Chest, Triceps | Intensity: 8/10
> ✨ Synced to Notion!

### 4. 🔖 Reading List & Content Routing
**Scope**: Saving articles, YouTube videos, and web links to read or watch later.
**How it Works**: Drop a valid HTTP link into the chat. The agent bypasses complex NLP models and auto-routes it directly into your Notion Reading Database.

**User:** 
> `https://medium.com/some-article-link`

**Bot:**
> I have logged the following:
> 🔖 Reading: 1 link(s) saved
> ✨ Synced to Notion!

### 5. 📊 Habit Tracking
**Scope**: Monitoring repetitive behaviors (positive or negative) to stay mindful.
**How it Works**: Safely logs behaviors into dedicated categories: `lost_self_control`, `junk_food`, `outside_food`, `late_eating`, `screen_time`, and `other` without losing the conversational context.

**User:** 
> "I lost my self control today and yelled at traffic, also watched netflix till 2am."

**Bot:**
> I have logged the following:
> 📊 Habit Tracker: Self Control: Yelled at traffic | Screen Time: Watched netflix till 2am
> 📝 Journal: I lost my self control today and yelled at traffic, also watched netflix till 2am.
> ✨ Synced to Notion!

### 6. 🧠 Natural Language Analytics
**Scope**: Querying your BigQuery database using normal human questions.
**How it Works**: Ask a question. The `Query Node` converts your question into strict executable BigQuery SQL, runs the mathematical analysis against your stored tables, and replies naturally.

**User:** 
> "What was my average mood this week?"

**Bot:**
> You had an average mood of 7.5 over the last 7 days!

---

## 📁 File Organization & Component Interaction

The repository is modularly designed, separating the generic Agent pipeline from the Telegram Interface. Development clutter has been strictly removed to ensure a clean production image.

```text
├── Dockerfile                    # Containerization instructions
├── Makefile                      # Make commands for testing, evals, format
├── simulation.py                 # CLI simulation script (bypasses Telegram for fast testing)
├── src/
│   └── life_os/
│       ├── agent/                # Core LangGraph agent definitions
│       │   ├── graph.py          # State graph wiring and execution compilation
│       │   ├── state.py          # Agent state typings
│       │   ├── prompts/          # System prompts for GPT-4o extractions & SQL Generation
│       │   └── nodes/            # 
│       │       ├── classifier.py # Routes to log, query, or chitchat
│       │       ├── extractor.py  # Uses Instructor to pull Pydantic models from text; handles merge logic
│       │       ├── persister.py  # Formats confirmation message & pushes to BigQuery/Notion
│       │       ├── query.py      # LLM powered native BigQuery SQL Analytics logic 
│       │       └── guard.py      # Prompt injection safety checks
│       ├── config/               # Pydantic env settings and structlog config
│       ├── evals/                # Custom evaluation datasets & F1 metric tracking (Mock-based)
│       ├── integrations/         # 
│       │   ├── bigquery_store.py # Async BigQuery clients supporting Cloud Run bindings
│       │   └── notion_store.py   # Tenacity-retried API calls to Notion databases
│       ├── models/               # 
│       │   ├── wellness.py       # Sleep, Exercise, and Wellness schemas (Including Habit Tracking)
│       │   └── tasks.py          # Task and ReadingLink schemas
│       └── telegram/             
│           ├── bot.py            # python-telegram-bot webhook handlers and polling core
│           └── jobs.py           # APScheduler cron jobs (morning check-in, weekly digest)
├── tests/
│   ├── integration/              # Pytest Asyncio tests covering LangGraph node chaining logic
│   └── unit/                     # Unit tests for LLM extractor accuracy and edge cases
```

---

## 🚀 Installation & Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/vaibhavd030/My-Tele-PA.git
   cd My-Tele-PA
   ```

2. **Install `uv` (Fast Python Package Installer)**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **Sync Dependencies**
   ```bash
   uv sync
   ```

4. **Environment Setup**
   Copy the `.env.example` file and populate your keys. At minimum, you need an OpenAI API Key and a Telegram Bot token (from BotFather). Enable Notion sync by setting `ENABLE_NOTION=true` and providing the relevant Page/Database IDs.
   ```bash
   cp .env.example .env
   ```

5. **Initialize Database**
   The BigQuery structured databases are automatically instantiated with required dataset schemas when you start up the FastAPI bot. Checkpointer states will gracefully save to `/data`. 
   ```bash
   make dev
   ```

---

## 🧪 Running the Project

### Local Execution (Polling Mode)
Run the script to actively ping Telegram servers for incoming app messages.
```bash
make dev
```

### Local Simulation (Bypass Telegram)
Useful for testing agent logic quickly without accessing your phone.
```bash
uv run python simulation.py
```

### Evaluations and Tests
A test suite handles node executions, and a custom CI evaluation script tracks Agentic metric parsing accuracy over `GPT-4o` without requiring live GCP credentials.
```bash
make test
make eval
```

---

## ☁️ Serverless Deployment

For 24/7 availability on a serverless architecture (meaning you pay $0.00 when the bot is not in use), the application can be seamlessly deployed to Google Cloud Run bounding to a Webhook instead of polling.

This setup securely provisions Cloud Storage FUSE to handle durable conversation `.db` checkpoints across container resets.

For the required environment variables and `gcloud` deployment commands securely configured for `us-central1` instances, see [deploy.md](deploy.md).
