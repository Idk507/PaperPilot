# Deploying PaperPilot to Google Cloud Run

This app reads `SECRET_KEY` (CSRF) and `COOKIE_SECURE` from the environment
(`app/settings.py`). There is no Azure OpenAI client.

Default GCP project used for this repo: `agenticproject-504506`.

## One-time setup

```bash
gcloud auth login
gcloud config set project agenticproject-504506
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
```

## Store the session secret (never in git)

```bash
printf "%s" "$(python -c "import secrets; print(secrets.token_hex(32))")" | gcloud secrets create SECRET_KEY --data-file=-
```

If `SECRET_KEY` already exists, add a new version instead of create.

## Deploy

```bash
gcloud run deploy paperpilot \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-secrets=SECRET_KEY=SECRET_KEY:latest \
  --set-env-vars=COOKIE_SECURE=true,DATABASE_URL=sqlite:////tmp/paperpilot.db,UPLOADS_DIR=/tmp/uploads \
  --memory=512Mi \
  --min-instances=0 \
  --max-instances=3
```

Cloud Run prints a `*.run.app` URL. Use that for Devpost and WebMCP testing.

**Live service (this project):** https://paperpilot-617103164879.us-central1.run.app

## Known Cloud Run gotchas

- **Ephemeral filesystem**: SQLite and uploads in `/tmp` do not survive new revisions. Fine for a demo.
- **Cold starts**: `--min-instances=0` sleeps when idle. Use `--min-instances=1` before judging if you want to avoid that.
- **Redeploy**: run the same `gcloud run deploy` command after code changes.
