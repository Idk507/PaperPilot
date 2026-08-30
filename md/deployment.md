# GCP_DEPLOY_PROMPT.md — PaperPilot on Google Cloud Run

Paste everything below the `---` line directly into Cursor as a single message. It's
self-contained and references the existing project docs, so Cursor doesn't need anything
else in context beyond the repo itself.

---

I need you to add Google Cloud Run deployment support to this repo (PaperPilot — FastAPI
backend, Jinja2 templates, SQLModel/SQLite, `services/parsing.py` uses `pdfplumber` and
`pytesseract` for document extraction). Follow `INSTRUCTIONS.md` and `ARCHITECTURE.md`'s
conventions for anything you touch. Do the following, in order:

## 1. Create `Dockerfile` at repo root

Cloud Run needs a container. Buildpacks (Python-only auto-detection) won't install the
`tesseract-ocr` system binary that `pytesseract` needs, so we use an explicit Dockerfile:

```dockerfile
FROM python:3.11-slim

# System dependency for pytesseract (OCR fallback in services/parsing.py's document
# extraction — see ARCHITECTURE.md's extract_from_document tool)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run injects PORT at runtime (default 8080) — must bind to it, not a hardcoded port
ENV PORT=8080
EXPOSE 8080

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
```

## 2. Create `.dockerignore` at repo root

```
.venv/
__pycache__/
*.pyc
.env
.git/
.pytest_cache/
*.db
tests/
```

## 3. Create `.gcloudignore` at repo root (same content as `.dockerignore` is fine)

## 4. Verify `requirements.txt` is frozen and complete

Run `pip freeze` in the project's virtualenv and confirm every import used in `app/`
appears in `requirements.txt` — Cloud Build will fail opaquely if a dependency is missing,
and that failure is harder to debug than a local one.

## 5. Do NOT commit secrets

Confirm no `.env` file, API keys, or credentials are tracked in git. This project doesn't
call an external LLM (see `ARCHITECTURE.md` — `explain_field` and `check_eligibility` are
rule-based, not LLM-backed), so the only sensitive value is `SESSION_SECRET` — confirm it's
read via `os.environ` in `app/main.py`, never hardcoded.

## 6. Add a `DEPLOY_GCP.md` documenting the manual `gcloud` steps

Create this file with the following content so a human can actually run the deployment
(you cannot run `gcloud` yourself — this is a doc for the person to follow):

```markdown
# Deploying PaperPilot to Google Cloud Run

## One-time setup

    gcloud auth login
    gcloud projects create paperpilot-hackathon --set-as-default
    gcloud config set project paperpilot-hackathon
    gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

## Store the session secret in Secret Manager (never in code or env files)

    printf "%s" "$(openssl rand -hex 32)" | gcloud secrets create SESSION_SECRET --data-file=-

## Deploy (builds the Dockerfile automatically via Cloud Build, then deploys to Cloud Run)

    gcloud run deploy paperpilot \
      --source . \
      --region us-central1 \
      --allow-unauthenticated \
      --set-secrets=SESSION_SECRET=SESSION_SECRET:latest \
      --set-env-vars=DATABASE_URL=sqlite:///./paperpilot.db \
      --memory=512Mi \
      --min-instances=0 \
      --max-instances=3

Cloud Run prints a `*.run.app` URL when this finishes — that's your live app URL for the
Devpost submission and for WebMCP testing (see the project's `DEPLOYMENT.md`, Part B).

## Known Cloud Run gotchas for this project

- **Ephemeral filesystem**: same caveat as Render — the SQLite file at `DATABASE_URL`
  does not persist across new revisions/deploys or container restarts. Fine for a demo;
  don't redeploy right before judging if you want your test data to persist. For real
  persistence, swap to Cloud SQL (Postgres) and update `DATABASE_URL` accordingly — no
  code changes needed elsewhere since SQLModel already talks to `DATABASE_URL` generically.
- **Cold starts**: `--min-instances=0` (the default here, to stay in the free tier) means
  the container spins down after inactivity and the next request pays a cold-start
  penalty. Set `--min-instances=1` before judging if you want to eliminate this — note it
  costs a small amount continuously while set.
- **Redeploying**: re-run the same `gcloud run deploy` command after any code change; it
  rebuilds and creates a new revision automatically, routing 100% of traffic to it.
```

