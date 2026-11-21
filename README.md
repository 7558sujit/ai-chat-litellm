# AI Chat — FastAPI + LiteLLM + SQLite

## 1. Live URLs
- Frontend: `https://<your-frontend>.vercel.app`
- Backend: `https://<your-backend>.onrender.com` (`/health`)

## 2. Run locally
**Docker:** `cp .env.example .env` (add 2+ real keys) → `make up` → UI http://localhost:3000, API http://localhost:8000. `make down` stops it; the `appdata` volume keeps history.

**Without Docker:**
```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
export LLM_API_KEYS=k1,k2 DATABASE_URL=sqlite:///./app.db ALLOWED_ORIGINS=http://localhost:3000 ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --port 8000
# frontend (any static server)
cd frontend && API_URL=http://localhost:8000 node build.js && npx serve dist -l 3000
```
Tests: `make test`.

**Deploy:** backend → Render/Railway/Fly (Docker, root `backend/`), attach a persistent disk at `/data`, set env vars from `.env.example` (`ALLOWED_ORIGINS` = frontend URL, `ENABLE_FAILURE_SIMULATION=true`). Frontend → Vercel/Netlify: root `frontend/`, build `node build.js`, output `dist`, env `API_URL` = backend URL.

## 3. Design decisions
- **Key fallback:** keys are tried in order (`key_1`, `key_2`…) via `litellm.acompletion(api_key=...)`. Any failure (429, quota, 5xx, timeout, auth, empty reply) moves to the next key; `fallback_attempts` counts failures. If all fail → `503 {"detail":"all providers unavailable"}` and nothing is saved. Keys are never returned or logged.
- **Caching:** LiteLLM's built-in in-memory cache (`litellm.Cache(type="local")`). Its key is model + full message list (+ temperature); the API key isn't part of it, so a cached answer is valid regardless of which key produced it. `cache_hit` from LiteLLM decides `LLM_CACHE` vs `LIVE_INFERENCE`. Cached replies return the stored usage, `key_id=null`. Cache is per process and is cleared on restart (history in SQLite is not).
- **SQLite sessions:** `messages` table per the spec plus a `sessions` table for the per-session system prompt. Schema is created on startup; path from `DATABASE_URL`. A user+assistant pair is written in one transaction only after a successful reply, so 422/503 never touch history.
- **Failure hook:** `X-Simulate-Failure` is parsed only if `ENABLE_FAILURE_SIMULATION=true`; the named keys raise inside the key loop (that request only) and cache reads are bypassed so failover genuinely runs and returns a real answer.

## 4. Verification
```bash
B=https://<backend>
curl -s -XPOST $B/chat -H 'content-type: application/json' -d '{"session_id":"t1","message":"Capital of France?"}'   # LIVE_INFERENCE
curl -s -XPOST $B/chat -H 'content-type: application/json' -d '{"session_id":"t2","message":"Capital of France?"}'   # LLM_CACHE, key_id null
curl -s -XPOST $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: key_1=429' -d '{"session_id":"t3","message":"hi"}'  # key_id key_2, fallback_attempts 1
curl -s -XPOST $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: *=429' -d '{"session_id":"t4","message":"hi"}'     # 503
curl -s $B/sessions/t1/messages
```
Token counts and source appear under every reply in the UI (`meta-*` test ids).

## 5. Setup Used
Editor: <fill in>. AI tools: Claude (scaffolding, tests), LiteLLM docs.

## 6. Bonus features
- Optional per-session system prompt field (`system-prompt-input`).
- Dark mode, non-root Docker user, `make test`.
