# llms.txt Generator

A web app that crawls any website and generates a spec-compliant [`llms.txt`](https://llmstxt.org) file — the emerging standard for telling LLMs what a site is about and which pages matter.

Paste a URL, choose a coverage level, and get a clean `llms.txt` in under a minute.

---

## How it works

1. **Crawl** — fetches the site via sitemap or BFS, rendering JavaScript with a headless browser
2. **Classify** — detects page types (guide, product, blog post, pricing, etc.)
3. **Score** — ranks pages by value to an LLM reader; drops low-signal pages
4. **Generate** — Claude assembles the final `llms.txt` with clean section groupings and descriptions

### Coverage levels

| Level | Pages crawled | Best for |
|---|---|---|
| Quick | ~25 | Homepage + core navigation |
| Standard | ~100 | Most websites |
| Comprehensive | ~200 | Docs, APIs, developer platforms |

---

## Development

### Requirements

- Python 3.12+
- Node.js 18+
- PostgreSQL

### Repo structure

```
/
├── frontend/        # Next.js 16 app (Vercel)
└── backend/         # FastAPI app (Railway)
```

### Backend setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
cp .env.example .env   # fill in values
alembic upgrade head
uvicorn main:app --reload
```

### Frontend setup

```bash
cd frontend
npm install
cp .env.example .env.local   # set NEXT_PUBLIC_API_URL
npm run dev
```

### Environment variables

**Backend** (`backend/.env`):

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | — | Claude API key |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed frontend origins (comma-separated) |
| `APP_ENV` | `development` | Set to `production` to disable debug endpoints |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model to use for generation |
| `JOB_TIMEOUT_S` | `600` | Max seconds per job before cancellation |
| `MAX_CONCURRENT` | `10` | Concurrent Chromium tabs per crawl (reduce for low-memory hosts) |
| `MONITOR_INTERVAL_HOURS` | `24` | How often the site monitor runs |
| `MONITOR_JOB_CONCURRENCY` | `1` | Max simultaneous monitor-triggered jobs |

**Frontend** (`frontend/.env.local`):

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend URL (e.g. `http://localhost:8000`) |

### Running tests

```bash
cd backend
pytest
```

### Deployment

- **Frontend** → Vercel (connect the `frontend/` directory)
- **Backend** → Railway (connect the `backend/` directory; Railway auto-detects the Dockerfile)
- **Database** → Railway Postgres plugin (injects `DATABASE_URL` automatically)

On Railway, set `APP_ENV=production` and all required env vars via the Variables panel.

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS v4 |
| Backend | FastAPI, Python 3.12 |
| Crawler | Crawl4AI (Playwright/Chromium) |
| AI | Anthropic Claude API |
| Database | PostgreSQL via SQLModel + Alembic |
