# CareFlow POC – Deploy

## Prerequisites

- **Env vars** (set in host or container, never commit `.env`):
  - `GOOGLE_API_KEY` – Gemini for chat/triage
  - `GOOGLE_MAPS_API_KEY` – Places API for doctors, pharmacy, labs, emergency
  - Optional: `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT` for LangSmith
  - Optional: `DATABASE_URL` for PostgreSQL; if unset, SQLite is used

---

## Deploy on Render

1. **Push your code** to GitHub or GitLab (ensure `.env` is not committed).

2. **Go to [Render Dashboard](https://dashboard.render.com)** → **New** → **Web Service**.

3. **Connect the repo** that contains `render.yaml` and select it. Render will detect the Blueprint.

   **Or** create the service manually:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path:** `/health`

4. **Add environment variables** (Dashboard → your service → **Environment**):
   - `GOOGLE_API_KEY` = your Gemini API key
   - `GOOGLE_MAPS_API_KEY` = your Google Maps/Places API key

5. **Deploy.** Render will build and start the app. Your app will be at:
   - **URL:** `https://<your-service-name>.onrender.com`
   - **UI:** `https://<your-service-name>.onrender.com/ui`
   - **Health:** `https://<your-service-name>.onrender.com/health`

**Note:** On the free tier, the service may spin down after ~15 minutes of no traffic; the first request after that can take 30–60 seconds (cold start). SQLite data is ephemeral on redeploys.

---

## Option 1: Docker

```bash
# Build
docker build -t careflow-poc .

# Run (pass env from host or use --env-file with a non-committed file)
docker run -p 8000:8000 \
  -e GOOGLE_API_KEY=your_key \
  -e GOOGLE_MAPS_API_KEY=your_maps_key \
  careflow-poc
```

- UI: http://localhost:8000/ui  
- Health: http://localhost:8000/health  

## Option 2: Bare server (e.g. Ubuntu)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export GOOGLE_API_KEY=...
export GOOGLE_MAPS_API_KEY=...
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Health check

- **GET /health** → `{"status":"ok"}` (use this for load balancers / orchestrators).

## Notes

- SQLite DB is created on first run (`careflow.db` in working dir). For multi-process or scale, switch to PostgreSQL via `DATABASE_URL`.
- For production, run behind a reverse proxy (nginx/Caddy) and set `DEBUG=false` (or omit) in env.
