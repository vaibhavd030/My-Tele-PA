**My-Tele-PA v3.0**  
life-os-agent
Wellness Overhaul, Habit Tracker & Apple Health Integration

Implementation Plan & Technical Specification

March 2026

# **1\. Progress Since Last Review**

Before diving into the new features, I want to acknowledge the significant improvements you have already shipped since the last review. The codebase is substantially more production-ready:

* AsyncSqliteSaver replaces MemorySaver: durable checkpoints across restarts.

* Centralised client factory (clients.py): single OpenAI/Instructor client with cost tracking.

* httpx replaces urllib: SSL verification is no longer disabled.

* LLM-based guardrails: SafetyClassification via Instructor replaces the regex approach.

* Text2SQL query node: replaces the pandas-dump-to-markdown approach.

* Clarification TTL: 30-minute expiry prevents stale context merging.

* Reset node at graph START: prevents entity bleed between conversations.

* OpenTelemetry tracing: every node is wrapped with trace spans.

* Voice note handling: Whisper transcription with retry logic.

* Webhook mode with FastAPI: proper Cloud Run deployment with /health endpoint.

* Alembic migrations: initial schema migration in place.

* Generic Notion sync dispatcher: SyncConfig dataclass pattern eliminates duplication.

* Expanded test suite: unit tests for classifier, persister, query, sqlite roundtrip, plus e2e flow tests.

The architecture is now solid enough to support the three major feature additions outlined in this document.

# **2\. Remaining Gaps to Fix First**

Before implementing new features, these issues in the current codebase should be addressed to avoid compounding technical debt.

## **2.1 Extractor Still Has a Type Bug**

Line 38 of extractor.py references 'date' in the type annotation of \_call\_llm (today: date) but the import is 'from datetime import datetime, timezone'. The 'date' type is imported inside the run() function body with 'from datetime import date'. This works at runtime because the @retry decorator defers evaluation, but mypy will flag it. Move the date import to the top of the file.

## **2.2 Extractor test\_extracts\_sleep\_data Is Broken**

The test patches \_call\_llm to return a plain ExtractedData, but the updated \_call\_llm now returns a tuple of (ExtractedData, tokens, cost). The mock needs to return a tuple: AsyncMock(return\_value=(mock\_result, 100, 0.001)).

## **2.3 Settings Model Validator Still Restricts Models**

The validate\_model allowlist is still {gpt-4o-mini, gpt-4o, gpt-4-turbo}. With gpt-4.1 and o-series models now available, this validator will break when you want to upgrade. Either remove the allowlist entirely or change it to a prefix check that accepts any model starting with 'gpt-' or 'o'.

## **2.4 Query Node SQL Injection Surface**

The Text2SQL node executes LLM-generated SQL directly. While there is a SELECT-only check, the LLM could generate 'SELECT \* FROM records; DROP TABLE records;'. Use parameterised queries and wrap execution in a read-only transaction:

await db.execute('BEGIN TRANSACTION')

cursor \= await db.execute(sql\_query)

await db.execute('ROLLBACK')  \# read-only, never commit

## **2.5 Sleep Quality Changed from Enum to Integer but Prompt Not Updated**

The SleepEntry model now uses quality: int (1-10) but the extraction prompt still says 'bucket them into the allowed categories'. Update the prompt to instruct the LLM to produce an integer 1-10 for sleep quality.

# **3\. Wellness Model Overhaul**

The current WellnessEntry is a single flat model that handles all meditation types, mood, and energy in one object. This causes several problems: (a) a user who does both meditation and cleaning in the same day can only log one, (b) each practice type has unique fields (e.g., 'took from' for sitting, 'place' for group meditation) that do not fit in a generic model, and (c) the Notion sync writes everything to a single wellness page rather than separate practice-specific pages.

## **3.1 New Pydantic Models**

Replace the single WellnessEntry with four separate practice-specific models, each with a shared base:

**Base Class**

class PracticeBase(BaseModel):

    """Base for all spiritual practices."""

    date: dt\_date

    datetime\_logged: dt\_datetime | None \= Field(

        default=None,

        description=(

            "The datetime when the practice was done. "

            "If user specifies a time, combine with date. "

            "If not specified, leave null and system will auto-fill."

        ),

    )

    duration\_minutes: Annotated\[int, Field(ge=1, le=300)\] | None \= None

    notes: str | None \= Field(default=None, max\_length=1000)

**1\. MeditationEntry**

class MeditationEntry(PracticeBase):

    """General / unspecified meditation session."""

    pass  \# base fields are sufficient

**2\. CleaningEntry**

class CleaningEntry(PracticeBase):

    """Heartfulness cleaning practice session."""

    pass  \# base fields are sufficient

**3\. SittingEntry**

class SittingEntry(PracticeBase):

    """Heartfulness sitting / transmission practice."""

    took\_from: str | None \= Field(

        default=None,

        description="Name of the trainer/preceptor who gave the sitting"

    )

**4\. GroupMeditationEntry**

class GroupMeditationEntry(PracticeBase):

    """Satsang / group meditation session."""

    place: str | None \= Field(

        default=None,

        description="Location/venue of the group meditation"

    )

**Update ExtractedData**

class ExtractedData(BaseModel):

    sleep: SleepEntry | None \= None

    exercise: list\[ExerciseEntry\] \= Field(default\_factory=list)

    meditation: list\[MeditationEntry\] \= Field(default\_factory=list)

    cleaning: list\[CleaningEntry\] \= Field(default\_factory=list)

    sitting: list\[SittingEntry\] \= Field(default\_factory=list)

    group\_meditation: list\[GroupMeditationEntry\] \= Field(default\_factory=list)

    habits: list\[HabitEntry\] \= Field(default\_factory=list)  \# Section 4

    tasks: list\[TaskItem\] \= Field(default\_factory=list)

    reading\_links: list\[ReadingLink\] \= Field(default\_factory=list)

    journal\_note: str | None \= None

    mood\_score: Annotated\[int, Field(ge=1, le=10)\] | None \= None

    energy\_level: Annotated\[int, Field(ge=1, le=10)\] | None \= None

Note: mood\_score and energy\_level are now top-level fields on ExtractedData rather than nested inside a wellness object. This makes them independent of any specific practice.

## **3.2 Datetime Auto-fill Logic**

The datetime\_logged field follows this resolution order:

* If the user explicitly says a time (e.g., 'did my sitting at 6am'), the LLM extracts it and combines with the date.

* If the user does not mention a time, the LLM leaves datetime\_logged as null.

* In the persister node, before saving, auto-fill null datetime\_logged with datetime.now(tz) using the configured timezone.

**Persister Auto-fill Code**

from datetime import datetime

from zoneinfo import ZoneInfo

tz \= ZoneInfo(settings.timezone)

now \= datetime.now(tz)

for practice\_key in \['meditation','cleaning','sitting','group\_meditation'\]:

    items \= entities.get(practice\_key, \[\])

    for item in items:

        if isinstance(item, dict) and item.get('datetime\_logged') is None:

            item\['datetime\_logged'\] \= now.isoformat()

## **3.3 Clarification Follow-ups for Practices**

Update the missing-field checks in the extractor for each practice type:

* Meditation: ask for duration if missing.

* Cleaning: ask for duration if missing.

* Sitting: ask for duration if missing. Ask 'Who did you take the sitting from?' if took\_from is null (but only on first ask, do not re-ask).

* Group meditation: ask for duration if missing. Ask 'Where was the group meditation?' if place is null (first ask only).

**Extractor Missing-field Logic**

for practice\_type in \['meditation','cleaning','sitting','group\_meditation'\]:

    items \= serialized.get(practice\_type, \[\])

    for item in items:

        if isinstance(item, dict):

            if not item.get('duration\_minutes'):

                field \= f'{practice\_type} duration'

                if field not in missing and field not in prior\_missing:

                    missing.append(field)

            if practice\_type \== 'sitting' and not item.get('took\_from'):

                if 'sitting trainer' not in missing and 'sitting trainer' not in prior\_missing:

                    missing.append('sitting trainer')

            if practice\_type \== 'group\_meditation' and not item.get('place'):

                if 'group meditation place' not in missing

                        and 'group meditation place' not in prior\_missing:

                    missing.append('group meditation place')

## **3.4 Separate Notion Pages**

Add four new Notion page ID settings and four new SyncConfig entries:

**Settings Additions**

notion\_meditation\_page\_id: str | None \= Field(default=None)

notion\_cleaning\_page\_id: str | None \= Field(default=None)

notion\_sitting\_page\_id: str | None \= Field(default=None)

notion\_group\_meditation\_page\_id: str | None \= Field(default=None)

notion\_habit\_page\_id: str | None \= Field(default=None)

**Notion Block Builders**

Each practice type gets its own block builder function. Example for SittingEntry:

async def \_build\_sitting(items: list\[SittingEntry\]) \-\> list\[dict\]:

    blocks \= \[\]

    for s in items:

        dt\_str \= s.datetime\_logged.strftime('%d %B %Y %I:%M%p')

            if s.datetime\_logged else \_format\_date\_only(s.date)

        text \= f'🧘 {dt\_str} | {s.duration\_minutes} mins'

        if s.took\_from:

            text \+= f' | From: {s.took\_from}'

        if s.notes:

            text \+= f' | {s.notes}'

        blocks.append(\_bullet\_block(text))

    return blocks

## **3.5 Update Extraction Prompt**

Replace rules 7 and 11 in extract.txt with:

7\. Spiritual practice classification (these are SEPARATE lists, not a single object):

   \- 'meditation' list \-\> general/unspecified meditation. Fields: date, datetime\_logged, duration\_minutes, notes.

   \- 'cleaning' list \-\> Heartfulness cleaning. Fields: date, datetime\_logged, duration\_minutes, notes.

   \- 'sitting' list \-\> Heartfulness sitting/transmission. Fields: date, datetime\_logged, duration\_minutes, took\_from, notes.

   \- 'group\_meditation' list \-\> satsang/group sitting. Fields: date, datetime\_logged, duration\_minutes, place, notes.

   If the user says 'did my cleaning for 30 mins' \-\> populate cleaning list.

   If the user says 'sat for group meditation at the centre' \-\> populate group\_meditation with place='the centre'.

   If the user says 'took sitting from Daaji' \-\> populate sitting with took\_from='Daaji'.

   NEVER put spiritual practices in the exercise list. Yoga IS exercise; meditation is NOT.

# **4\. Habit Tracker**

The habit tracker captures negative habits and indulgences that the user wants to be aware of. Unlike other entities which are structured, habit tracking is open-ended: the user describes what happened and the system classifies it.

## **4.1 Pydantic Model**

class HabitCategory(StrEnum):

    SELF\_CONTROL \= "lost\_self\_control"

    JUNK\_FOOD \= "junk\_food"

    OUTSIDE\_FOOD \= "outside\_food"

    LATE\_EATING \= "late\_eating"

    SCREEN\_TIME \= "screen\_time"

    OTHER \= "other"

class HabitEntry(BaseModel):

    """A habit event to track (typically negative habits to be mindful of)."""

    date: dt\_date

    datetime\_logged: dt\_datetime | None \= None

    category: HabitCategory

    description: str \= Field(

        description='What happened, e.g. ate ice cream, ordered Deliveroo, watched Netflix till 2am'

    )

    notes: str | None \= None

## **4.2 Extraction Prompt Addition**

12\. HABIT TRACKER: If the user mentions any of these patterns, extract a habit entry:

   \- Lost self-control, gave in to temptation \-\> category='lost\_self\_control'

   \- Ate junk food, chips, sweets, ice cream, chocolate \-\> category='junk\_food'

   \- Ordered food delivery, Deliveroo, UberEats, ate out \-\> category='outside\_food'

   \- Ate after 8pm, late dinner, midnight snack \-\> category='late\_eating'

   \- Watched movie/Netflix/YouTube for hours, doom scrolling \-\> category='screen\_time'

   \- Any other negative habit the user wants to track \-\> category='other'

   The 'description' field should be a short factual summary of what happened.

   A single message can contain MULTIPLE habit entries.

## **4.3 Notion Sync**

Create a dedicated Notion page for habits. Each entry is appended as a bulleted list item with category emoji:

\_HABIT\_ICONS \= {

    "lost\_self\_control": "🔴",

    "junk\_food": "🍔",

    "outside\_food": "🛵",

    "late\_eating": "🌙",

    "screen\_time": "📺",

    "other": "⚠️",

}

async def \_build\_habits(items: list\[HabitEntry\]) \-\> list\[dict\]:

    blocks \= \[\]

    for h in items:

        icon \= \_HABIT\_ICONS.get(h.category, '⚠️')

        dt\_str \= h.datetime\_logged.strftime('%d %B %I:%M%p')

            if h.datetime\_logged else \_format\_date\_only(h.date)

        text \= f'{icon} {dt\_str} | {h.category.replace("\_"," ").title()}: {h.description}'

        if h.notes:

            text \+= f' | {h.notes}'

        blocks.append(\_bullet\_block(text))

    return blocks

## **4.4 No Clarification for Habits**

Habit entries should never trigger a clarification loop. If the user says 'ate ice cream', log it immediately with category=junk\_food and description='ate ice cream'. Do not ask for time or notes. The datetime auto-fill logic from Section 3.2 applies.

# **5\. Journal Integration**

The journal\_note field in ExtractedData must now include ALL tracked activities in its narrative, including the new practice types and habit entries.

## **5.1 Updated Journal Prompt Rule**

10\. ALWAYS write a journal\_note summarizing the user's entire message into a cohesive

    first-person narrative string.

    \- Include ALL activities: sleep, exercise, meditation, cleaning, sitting,

      group meditation, habits, tasks, mood, energy, meals.

    \- EVEN IF extracted into structured fields, still mention in the journal.

    \- For habits, phrase them reflectively: 'I noticed I ate junk food today \-

      something to be mindful of.'

    \- EXCEPTION: clarification replies and bare URLs get null journal\_note.

## **5.2 Persister Journal Section**

Update the persister to include new entity types in the confirmation message and to build a comprehensive journal entry for Notion that aggregates all logged data:

\# Add icons for new types

\_ICONS.update({

    "meditation": "🧘 Meditation",

    "cleaning": "🧹 Cleaning",

    "sitting": "🪷 Sitting",

    "group\_meditation": "🕊️ Group Meditation",

    "habits": "📊 Habit Tracker",

    "mood": "😊 Mood",

    "energy": "⚡ Energy",

})

# **6\. Apple Health Integration**

Apple Health (HealthKit) does not expose a REST API. There is no way to query Apple Health data directly from a Python backend. However, there are three viable approaches, ranked by automation level.

## **6.1 Approach A: Health Auto Export App (Recommended)**

Health Auto Export is a well-maintained iOS app (by Lybron Sobers) that reads Apple HealthKit data and pushes it to a REST API endpoint via HTTP POST. This is the standard approach used by most Apple Health integration projects in the wild.

**How It Works**

* Install Health Auto Export on your iPhone (premium subscription required for automated exports, or lifetime purchase available).

* Configure it to export sleep\_analysis data in JSON format.

* Set the REST API endpoint to your Cloud Run service URL (e.g., https://your-service.run.app/api/apple-health/ingest).

* Configure export frequency (e.g., every 6 hours or on wake).

* The app pushes sleep data automatically; your backend receives it, parses it, and stores it in SQLite \+ syncs to Notion.

**Backend Implementation**

Add a new FastAPI endpoint to bot.py (webhook mode):

@app.post('/api/apple-health/ingest')

async def ingest\_apple\_health(request: Request) \-\> dict:

    """Receive Apple Health data from Health Auto Export app."""

    auth \= request.headers.get('Authorization')

    if auth \!= f'Bearer {settings.apple\_health\_token}':

        raise HTTPException(status\_code=401)

    payload \= await request.json()

    records \= parse\_apple\_health\_sleep(payload)

    if records:

        await save\_records(user\_id=str(settings.telegram\_chat\_id), records=records)

        \# Optionally sync to Notion

        for record in records:

            sleep\_entry \= SleepEntry(\*\*record)

            await sync\_sleep\_to\_notion(sleep\_entry)

    return {'status': 'ok', 'records\_saved': len(records)}

**Sleep Data Parser**

def parse\_apple\_health\_sleep(payload: dict) \-\> list\[dict\]:

    """Parse Health Auto Export JSON payload into SleepEntry-compatible dicts."""

    records \= \[\]

    metrics \= payload.get('data', {}).get('metrics', \[\])

    for metric in metrics:

        if metric.get('name') \!= 'sleep\_analysis':

            continue

        for data\_point in metric.get('data', \[\]):

            \# Health Auto Export provides sleep phases with start/end times

            start \= datetime.fromisoformat(data\_point\['date'\])

            qty \= data\_point.get('qty', 0\)  \# duration in hours

            records.append({

                'type': 'sleep',

                'date': start.date().isoformat(),

                'source': 'apple\_health',

                'bedtime\_hour': start.hour,

                'bedtime\_minute': start.minute,

                'duration\_hours': round(qty, 2),

                'quality': \_infer\_quality(qty),

            })

    return records

**Deduplication**

Since the app may push overlapping data, add a dedup check before saving:

async def save\_if\_not\_duplicate(user\_id: str, record: dict) \-\> bool:

    db \= await get\_db()

    cursor \= await db.execute(

        'SELECT id FROM records WHERE user\_id=? AND date=? AND type=?'

        ' AND json\_extract(data, "$.source")="apple\_health"',

        (user\_id, record\['date'\], 'sleep'),

    )

    if await cursor.fetchone():

        return False  \# already have this day

    await save\_records(user\_id, \[record\])

    return True

**Settings Addition**

apple\_health\_token: str | None \= Field(

    default=None, description='Bearer token for Apple Health ingest endpoint'

)

## **6.2 Approach B: Manual XML Export \+ Telegram Upload**

For a zero-cost option without subscription apps: the user periodically exports Apple Health data (Settings \> Health \> Export All Health Data), uploads the export.zip to the Telegram bot, and the bot parses it.

**Implementation**

\# Add a document handler to bot.py

async def handle\_document(update, context):

    doc \= update.message.document

    if doc.file\_name.endswith('.zip'):

        \# Download, extract, parse export.xml

        file \= await context.bot.get\_file(doc.file\_id)

        buffer \= io.BytesIO()

        await file.download\_to\_memory(out=buffer)

        records \= parse\_apple\_health\_xml(buffer)

        await save\_records(user\_id, records)

Drawback: manual, infrequent, and the export.xml can be hundreds of MB for long-time users. Best as a one-time historical import, not ongoing sync.

## **6.3 Approach C: iOS Shortcuts \+ Webhook**

Create an iOS Shortcut that triggers on a schedule (e.g., each morning), reads the latest sleep data from HealthKit, formats it as JSON, and sends an HTTP POST to your webhook. This is free but requires manual Shortcut setup and is limited in what HealthKit data Shortcuts can access.

Verdict: Approach A (Health Auto Export) is the most reliable and lowest-maintenance option. The app costs a one-time premium purchase and handles background syncing, retries, and data formatting.

## **6.4 Architecture Diagram**

The data flow for Apple Health integration:

iPhone (Apple Watch/Health) 

    \-\> Apple HealthKit (on-device)

    \-\> Health Auto Export app (reads HealthKit, runs in background)

    \-\> HTTP POST to Cloud Run /api/apple-health/ingest

    \-\> parse\_apple\_health\_sleep()

    \-\> Dedup check

    \-\> SQLite save\_records() \+ Notion sync

    \-\> Optional: Send Telegram notification with sleep summary

# **7\. Database Migration**

The new models require an Alembic migration to add a 'source' column for distinguishing manual entries from Apple Health imports, and updated type values for the new practice types.

## **7.1 New Alembic Migration**

def upgrade() \-\> None:

    op.add\_column('records', sa.Column('source', sa.String(), default='manual'))

    op.create\_index('ix\_records\_date\_type', 'records', \['date', 'type'\])

    op.create\_index('ix\_records\_user\_type', 'records', \['user\_id', 'type'\])

## **7.2 New Record Types**

The 'type' column in the records table will now accept these additional values: meditation, cleaning, sitting, group\_meditation, habit, mood, energy. The existing 'wellness' type is deprecated; old records should still be queryable but new records use the specific types.

# **8\. Implementation Roadmap**

## **Phase 1: Bug Fixes & Prep (1 day)**

* Fix extractor date import (2.1).

* Fix test mock return type (2.2).

* Expand model validator or remove it (2.3).

* Add read-only transaction wrapper for Text2SQL (2.4).

* Update sleep quality prompt to integer (2.5).

## **Phase 2: Wellness Model Overhaul (2-3 days)**

* Create PracticeBase and four practice models (3.1).

* Remove old WellnessEntry and MeditationType from wellness.py.

* Update ExtractedData to use new practice lists (3.1).

* Implement datetime auto-fill in persister (3.2).

* Add practice-specific missing-field checks in extractor (3.3).

* Add 5 new Notion page ID settings (3.4).

* Write Notion block builders for each practice type (3.4).

* Register new SyncConfigs in notion\_store.py (3.4).

* Rewrite extraction prompt rules 7 and 11 (3.5).

* Update persister summary/confirmation messages.

* Create Alembic migration (7.1).

* Write unit tests for each new model, extraction, and persistence.

* Add eval cases: 'did cleaning for 20 mins', 'took sitting from Daaji at 6am for 30 mins', 'group meditation at the ashram'.

## **Phase 3: Habit Tracker (1-2 days)**

* Create HabitCategory enum and HabitEntry model (4.1).

* Add habit extraction prompt rule (4.2).

* Write Notion block builder for habits (4.3).

* Add habit\_page\_id to settings.

* Register habit SyncConfig.

* Update journal prompt to include habits (5.1).

* Update persister to handle habit entities.

* Write tests: 'ate ice cream late at night' should produce both junk\_food and late\_eating entries.

* Add eval cases for habit extraction.

## **Phase 4: Journal Enhancement (1 day)**

* Update journal prompt rule 10 to cover all new entity types (5.1).

* Update persister confirmation message to show all new sections (5.2).

* Ensure mood\_score and energy\_level are persisted as separate record types.

## **Phase 5: Apple Health Integration (2-3 days)**

* Add /api/apple-health/ingest endpoint to FastAPI (6.1).

* Implement parse\_apple\_health\_sleep() (6.1).

* Add dedup logic (6.1).

* Add apple\_health\_token to settings.

* Add Alembic migration for source column (7.1).

* Configure Health Auto Export app on iPhone.

* Test end-to-end with real sleep data.

* Optional: send Telegram summary after Apple Health ingest.

## **Phase 6: Testing & Eval (1-2 days)**

* Unit tests for all new models (validation, edge cases).

* Unit tests for each new Notion block builder.

* Integration test: full graph flow with meditation \+ habit message.

* Eval dataset additions: 8-10 new extraction cases covering practices, habits, mixed messages.

* E2E test: Apple Health ingest endpoint.

Total estimated effort: 8-12 days across all phases.

# **9\. File Change Summary**

| File | Action | Changes |
| :---- | :---- | :---- |
| src/life\_os/models/wellness.py | Major edit | Remove WellnessEntry, MeditationType. Add PracticeBase, MeditationEntry, CleaningEntry, SittingEntry, GroupMeditationEntry, HabitCategory, HabitEntry. Update ExtractedData. |
| src/life\_os/config/settings.py | Edit | Add 5 Notion page IDs, apple\_health\_token. Fix model validator. |
| src/life\_os/agent/prompts/extract.txt | Major edit | Rewrite rules 7, 10, 11\. Add rule 12 for habits. Update datetime guidance. |
| src/life\_os/agent/nodes/extractor.py | Edit | Fix date import. Add missing-field checks for practices and habits. Update merge logic for new entity types. |
| src/life\_os/agent/nodes/persister.py | Major edit | Add datetime auto-fill. Add summary functions for 4 practices \+ habits. Handle new entity types. Update icons. |
| src/life\_os/integrations/notion\_store.py | Major edit | Add 5 block builders. Register 5 SyncConfigs. Remove old wellness builder. Add \_bullet\_block helper. |
| src/life\_os/integrations/sqlite\_store.py | Edit | Add save\_if\_not\_duplicate(). Update save\_records to handle source field. |
| src/life\_os/telegram/bot.py | Edit | Add /api/apple-health/ingest endpoint. Add parse\_apple\_health\_sleep(). |
| src/life\_os/agent/nodes/query.py | Edit | Add read-only transaction wrapper. Update SCHEMA\_PROMPT with new types. |
| alembic/versions/002\_\*.py | New | Add source column, date+type index, user+type index. |
| src/life\_os/evals/datasets/extraction.jsonl | Edit | Add 8-10 new eval cases for practices, habits, mixed messages. |
| tests/unit/test\_wellness\_models.py | New | Tests for all new Pydantic models and validation. |
| tests/unit/test\_apple\_health.py | New | Tests for Apple Health payload parsing and dedup. |

# **10\. Summary**

This plan delivers three major capabilities: (1) granular spiritual practice tracking with separate Notion pages, practice-specific fields, and intelligent clarification, (2) a habit tracker for mindful self-awareness with automatic categorisation, and (3) automated sleep data ingestion from Apple Health via the Health Auto Export app.

The key design decisions are: datetime is auto-filled by the system when not specified by the user; each practice type gets its own Pydantic model, Notion page, and SQLite record type; habit entries never trigger clarification; and Apple Health data flows through a dedicated ingest endpoint with deduplication. All new data is woven into the journal narrative for a complete daily record.

The changes are backwards-compatible: existing 'wellness' records in SQLite remain queryable, and the old WellnessEntry type is simply not produced anymore. The Alembic migration only adds columns and indexes, never drops existing data.