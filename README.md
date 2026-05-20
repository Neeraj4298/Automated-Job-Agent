# Autonomous Job Application System

A fully automated job application agent that discovers, qualifies, fills, and submits job applications using AI-powered decision making and human-like browser automation.

## Architecture

```
Scheduler → Agent Brain → Browser Engine ↔ Persistence Layer
                ↕
           AI (Claude/GPT)
                ↕
          Alert System (Email/Telegram)
```

| Layer | Tool | Purpose |
|-------|------|---------|
| Layer 1 — Scheduler | APScheduler | Triggers daily runs (08:00–21:00) |
| Layer 2 — Browser | Playwright + stealth | Navigates, fills forms, submits |
| Layer 3 — AI Brain | LangGraph + Claude | Decides, qualifies, personalizes |
| Layer 4 — Persistence | SQLite + SQLAlchemy | Deduplication, logs, job queue |

## Quick Start

### 1. Install dependencies

```bash
cd job_agent
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your real values (name, email, resume path, API keys, etc.)
```

### 3. Run tests

```bash
python -m pytest tests/ -v
```

### 4. Start the agent

```bash
# Dry run — no real submissions, full logging
DEBUG_MODE=true python main.py --dry-run

# Live run — starts APScheduler, runs within 08:00–21:00 window
python main.py
```

## Project Structure

```
job_agent/
├── main.py                  # Entry point + APScheduler
├── config.py                # Env-based config (pydantic)
├── .env                     # Your secrets (never commit)
├── .env.example             # Template
│
├── agent/
│   ├── graph.py             # LangGraph state machine
│   ├── state.py             # Shared AgentState type
│   └── nodes/               # 10 agent nodes
│
├── browser/
│   ├── engine.py            # Playwright + stealth setup
│   ├── timing.py            # Human-like delays
│   ├── useragents.py        # UA rotation pool
│   └── form_utils.py        # ATS detection + field helpers
│
├── db/
│   ├── models.py            # SQLAlchemy ORM
│   └── crud.py              # DB operations
│
├── ai/
│   ├── llm_client.py        # Claude/GPT wrapper
│   ├── prompts.py           # Prompt templates
│   └── keyword_extract.py   # TF-IDF + LLM extraction
│
├── alerts/
│   ├── email_alert.py       # SMTP email
│   └── telegram_alert.py    # Telegram bot
│
├── reports/
│   ├── daily_report.py      # CSV + HTML summary
│   └── templates/
│       └── summary.html
│
├── tests/                   # Pytest test suite
├── logs/                    # Rotating logs (gitignored)
└── queue/                   # Overflow jobs (gitignored)
```

## Configuration Reference

See `.env.example` for all available settings. Key variables:

| Variable | Description |
|----------|-------------|
| `RESUME_PATH` | Absolute path to your resume PDF |
| `ROLES` | Comma-separated job titles to search |
| `DAILY_MAX_APPLICATIONS` | Cap per day (default: 50) |
| `LOCATION_FILTER` | `remote`, `hybrid`, or city name |
| `ANTHROPIC_API_KEY` | Claude API key (primary AI) |
| `DEBUG_MODE` | `true` = no real submissions |
| `HEADLESS` | `false` = visible browser (good for debugging) |

## Known Limitations

1. **LinkedIn detection** — Keep under 8 apps/day; never run headless on LinkedIn.
2. **Workday/Taleo/iCIMS** — ATS platforms vary per company; separate handlers are included.
3. **CAPTCHAs** — System gracefully skips and queues for manual review (no bypass).
4. **Google rate limits** — Use `SERPAPI_KEY` for reliable search; free googlesearch gets blocked quickly.
5. **robots.txt** — All sites are checked before navigation; non-compliant sites are skipped.

## Deployment Options

| Option | Best For |
|--------|----------|
| **Local machine** | Testing, low volume |
| **VPS (DigitalOcean $6/mo)** | Production, 24/7 |
| **Docker** | Portability (`docker build . && docker run`) |
| **GitHub Actions** | Job discovery only (no browser persistence) |

See `Dockerfile` for containerized deployment.

## Legal & Ethics

- This system respects `robots.txt` on all target domains.
- It does **not** bypass CAPTCHAs or security mechanisms.
- It does **not** fabricate credentials or experience.
- It immediately halts if sensitive fields (SSN, bank account) are detected.
- You are responsible for complying with each job board's Terms of Service.
