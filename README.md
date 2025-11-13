# Lead Nurturing Agent Platform

An automation layer for real-estate sales teams built with **Django Ninja**, **LangGraph**, **ChromaDB**, and **Vanna**. The system lets associates shortlist CRM leads, launch personalized nurture campaigns, ingest brochure documents for retrieval augmented generation, and route inbound customer replies through an AI agent that can answer questions or escalate to goal actions (property visits or calls).

---

## Technology Stack

| Layer | Implementation | Notes                                                                                                                                                     |
| --- | --- |-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| Core backend | **Django 5** + **Django Ninja** | High-performance REST API with automatic OpenAPI docs                                                                                                     |
| AI orchestration | **LangGraph** | Routes between RAG and Text-to-SQL toolchains                                                                                                             |
| LLMs | **Google Gemini** (`GOOGLE_API_KEY`) | Defaults: `DEFAULT_GEMINI_MODEL` → `gemini-2.0-flash`; override with `VANNA_MODEL`, `PERSONALIZATION_MODEL`, `DOCUMENT_QUERY_MODEL`, `AGENT_ROUTER_MODEL` |
| Text-to-SQL | **Vanna** (local agent, `vanna.integrations.sqlite`) | Uses Gemini for reasoning and executes against SQLite                                                                                                     |
| Vector store | **ChromaDB** | Persisted under `CHROMA_DB_DIR` (defaults to `storage/chroma`)                                                                                            |
| Database | **SQLite** (`db.sqlite3`) | Swap to PostgreSQL by editing `DATABASES` in `config/settings.py`                                                                                         |
| Testing | **Pytest** | Unit & integration tests for shortlist, campaigns, ingestion, LangGraph                                                                                   |
| Evaluation | **DeepEval** | `run_eval.py` produces `agent_evaluation_scores.json`                                                                                                     |

---

## Prerequisites

- Python 3.13 (the repository already ships with a `.venv`; activate it before running commands).
- SQLite (default). PostgreSQL can be wired by editing `config/settings.py`.
- Git installed locally (required because `requirements.txt` pulls the Vanna package from GitHub).
- API credentials:
  - `GOOGLE_API_KEY` – Gemini access for embeddings, message generation, and the local Vanna agent.
  - `VANNA_MODEL` (optional) – Gemini model name for the Vanna agent. Defaults to `gemini-2.0-flash`.

Create a `.env` at the project root (do **not** commit secrets):

```bash
DJANGO_SECRET_KEY=replace-me
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost 127.0.0.1
GOOGLE_API_KEY=your-gemini-key
VANNA_MODEL=gemini-2.0-flash
CHROMA_DB_DIR=storage/chroma
BROCHURE_UPLOAD_DIR=media/brochures
LANGGRAPH_CHECKPOINT_DIR=storage/langgraph_checkpoints
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=demo.sender@gmail.com
EMAIL_HOST_PASSWORD=your-16-digit-app-password
DEFAULT_FROM_EMAIL=demo.sender@gmail.com
# All nurture emails will be routed here (single demo inbox)
CAMPAIGN_EMAIL_OVERRIDE=demo.recipient@gmail.com
```

---

## Initial Setup

```bash
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
# Optional: load sample CRM leads
python manage.py loaddata crm/fixtures/sample_leads.json
python manage.py createsuperuser  # optional, for Django admin
```

### Configure Gmail SMTP (single test inbox)

1. Enable 2-Step Verification on the Gmail account you want to send from.
2. Generate a new **App Password** (Security → App passwords) choosing `Mail` and a custom device name (e.g. `Proplens Demo`).
3. Copy the 16-character password Google displays.
4. Update `.env`:
   - `EMAIL_HOST_USER`: the Gmail address you are sending from.
   - `EMAIL_HOST_PASSWORD`: the 16-character app password (without spaces).
   - `DEFAULT_FROM_EMAIL`: usually the same Gmail address to keep headers consistent.
   - `CAMPAIGN_EMAIL_OVERRIDE`: the single inbox that should receive every nurture message (can be the same Gmail or another test mailbox).
5. Restart `python manage.py runserver` so Django picks up the new configuration.
6. Create a campaign; the personalized copy is emailed to the override inbox and recorded in `ConversationMessage.metadata.sent_to`.

### Development server

```bash
python manage.py runserver
```

OpenAPI docs are available at `http://localhost:8000/api/docs`.

---


## API Summary

| Method & Path | Description | Auth |
| --- | --- | --- |
| `POST /api/auth/token` | Obtain JWT access/refresh pair | No |
| `POST /api/auth/token/refresh` | Refresh access token | No |
| `POST /api/leads/shortlist` | Filter CRM leads (min. two filters required) | Bearer |
| `POST /api/campaigns/` | Create campaign, generate & dispatch personalized messages | Bearer |
| `GET /api/campaigns/{cid}/followups/{clid}` | Conversation thread pop-up data | Bearer |
| `POST /api/campaigns/followups/{clid}/respond` | Process customer reply via agent (nudges or goal handling) | Bearer |
| `POST /api/agent/documents/upload` | Upload brochure(s) → chunk, embed, persist | Bearer |
| `POST /api/agent/query` | Direct agent access (routes to SQL or RAG) | Bearer |

**Filter controls** (User Story 1):
- Project name, budget range, unit type, lead status, last conversation date range. Any two or more must be provided.

**Campaign creation** (User Stories 2 & 3):
- Accepts campaign project, channel (Email/WhatsApp), optional offer copy, and lead IDs from CRM shortlist.
- Each lead’s personalized email is generated with brochure context + CRM history and saved as the first message in the conversation log.

**Follow-up handling** (User Story 4):
- Customer replies are logged, the AI agent responds using LangGraph routing, and if goal intent is detected (visit / call), the system seals the goal and records the scheduled slot.

### API walkthrough (curl examples)

```bash
# 1. Obtain a JWT pair
curl -s -X POST http://127.0.0.1:8000/api/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "changeme"}'

# (store the response values)
export TOKEN=<access_token>
export REFRESH=<refresh_token>

# 2. Refresh the access token
curl -s -X POST http://127.0.0.1:8000/api/auth/token/refresh \
  -H "Content-Type: application/json" \
  -d "{\"refresh\": \"$REFRESH\"}"

# 3. Shortlist leads (any two filters required)
curl -s -X POST http://127.0.0.1:8000/api/leads/shortlist \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_names":["Altura"],"unit_types":["2 bed"],"lead_status":"connected"}'

# 4. Create a campaign + personalized emails
curl -s -X POST http://127.0.0.1:8000/api/campaigns/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Demo campaign","project_name":"Altura","message_channel":"email","offer_details":"50% off","lead_ids":[1,2],"filters_snapshot":{"project_names":["Altura"],"lead_status":"connected"}}'

# 5. Upload brochures (auto-detects project name when omitted)
curl -s -X POST http://127.0.0.1:8000/api/agent/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@/path/to/brochure.pdf"

# 6. Ask the AI agent a question (LangGraph routes to RAG or SQL)
curl -s -X POST http://127.0.0.1:8000/api/agent/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"campaign_lead_id": 1, "query": "Which amenities should I highlight?"}'

# 7. Retrieve conversation history for a lead
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/campaigns/<campaign_id>/followups/<campaign_lead_id>
```

---

## Document Ingestion Workflow

1. `POST /api/agent/documents/upload` with `multipart/form-data` (`files` field) and optional `project_name`.
2. Pipeline steps:
   - Store file under `BROCHURE_UPLOAD_DIR`.
   - Split content (PDF or text) via recursive character splitter.
   - Embed chunks using Gemini embeddings.
   - Save vectors + metadata to Chroma collection (`project_{normalized_name}` or fallback).
   - Log ingestion status in `DocumentIngestionLog`.

Uploaded brochures can be re-ingested; existing vectors for the same document ID are removed prior to insertion.

---

## LangGraph Agent Behaviour

1. **Router** – A Gemini classifier inspects the user question and chooses the SQL (Text-to-SQL) or RAG branch (falls back to keywords only if the classifier fails).
2. **T2SQL branch** – The local Vanna agent generates SQL, executes it through the embedded SQLite runner, and summarises the output.
3. **RAG branch** – Chroma retrieval → Gemini synthesis referencing lead history & campaign CTA.
4. **State checkpointing** – In-memory LangGraph saver (no on-disk checkpoint to stay lightweight).

---

## Testing & Evaluation

### Unit / integration tests

```bash
pytest
```
- If you need seed data quickly, run `python manage.py loaddata crm/fixtures/sample_leads.json`; those entries make the shortlisting/campaign UI respond immediately.

Tests cover:
- Lead shortlist validation & filtering.
- Campaign creation, initial agent message, follow-up responses, goal detection.
- Document ingestion API (with service stubs).
- LangGraph routing decisions (SQL vs RAG).

### DeepEval benchmarking

```bash
python run_eval.py
```

- Generates deterministic agent answers using stubbed RAG and T2SQL services.
- Runs two DeepEval metrics (keyword coverage & route accuracy).
- Outputs structured results to `agent_evaluation_scores.json` (retain for review).

> Note: Metrics purposely run in synchronous mode; additional hyperparameter logging can be enabled if desired.

### Full verification (tests + evaluation)

```bash
pytest && python run_eval.py
```

Running both commands in sequence validates the API flows and regenerates `agent_evaluation_scores.json` for audit purposes.

---

## Operational Notes

- Provide a valid **GOOGLE_API_KEY** so Gemini and the embedded Vanna agent can operate. Without it, Text-to-SQL generation will raise `ImproperlyConfigured`.
- Optional overrides: set `VANNA_MODEL`, `PERSONALIZATION_MODEL`, `DOCUMENT_QUERY_MODEL`, or `AGENT_ROUTER_MODEL` in `.env` to point each agent path at specific Gemini releases (e.g. `gemini-1.5-pro-latest` for personalization and `gemini-1.5-flash` for RAG/SQL).
- Chroma persistence directories are auto-created based on environment variables.
- Set `CAMPAIGN_EMAIL_OVERRIDE` to capture all nurture emails at a mock/demo address; otherwise messages go to each lead’s email on record.
- Email/WhatsApp delivery and external deployments are outside the scope of this challenge.
- Use Django admin (`/admin`) to inspect models (`Lead`, `Campaign`, `CampaignLead`, `ConversationMessage`, `BrochureDocument`).

---

## Next Steps (Optional Enhancements)

- Swap the in-memory LangGraph saver for a durable checkpoint store once concurrency requirements firm up.
- Extend campaign dashboards with sparkline/time-series metrics.
- Integrate actual email/WhatsApp delivery adapters.
- Harden Vanna integration with background training jobs and better SQL safety guards.
- Expand DeepEval coverage with human-labelled expectations once real campaign data is available.

