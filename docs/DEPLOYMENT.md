# Deployment Plan

Two independently deployable pieces:

- **backend** — FastAPI app (`backend/committee/api/main.py`), SQLite-backed, single process. Owns all state: `app.state.portfolio` (in-memory), the SQLite DB (decisions/trades/portfolio_snapshots), and the Breeze session.
- **frontend** — a static Vite/TypeScript bundle (no server-side rendering), served by nginx, talking to the backend purely over its public HTTP API.

Dockerfiles: `backend/Dockerfile`, `frontend/Dockerfile`. Local orchestration: `docker-compose.yml` at the repo root. Nothing below assumes a specific cloud provider — it's written for "a VM/host running Docker," with notes on what changes for a managed container platform (ECS/Cloud Run/App Service/etc).

**Policy: images are only ever built and published by CI (`.github/workflows/ci-cd.yml`), never `docker push`ed from a local machine.** `docker compose build`/`up` locally is for developing and smoke-testing a change on your own machine only — verify it there first. Pushing to `main` (after review) is what actually produces a published image, and only after both test jobs pass; see §8.

## 1. Architectural constraint that shapes everything below

**Run exactly one backend process. Not `--workers N`, not multiple replicas behind a load balancer.**

`app.state.portfolio` (`backend/committee/execution/portfolio.py`) is a single in-memory object — cash, positions, cost basis. It is not persisted to the DB (only `portfolio_snapshots`, a read-only history, is) and it is not shared across processes. Two uvicorn workers, or two replicas of the backend container, would each hold their own independent `Portfolio`, silently diverging the moment a trade lands in one but not the other. There is currently no code path that makes this safe — scaling the backend horizontally is a rewrite (portfolio state would need to move into the DB behind a lock/transaction), not a deployment setting.

Practically: one container, no replica count > 1, no `uvicorn --workers`. If you need the API to survive a container restart without losing open positions, that's a separate, currently-unsolved gap (see `Portfolio`'s own docstring: "In-memory only, not persisted/restored across a process restart... acceptable for a single-session demo").

## 2. Env safety

**Principle: secrets live in the deployment environment (host env vars / your platform's secret store), never in the image or in git.**

- `.env` is git-ignored already (see `.gitignore`) and must stay that way. It's for local dev only.
- `pydantic-settings` (`backend/committee/config.py`) reads `.env` but real environment variables always take precedence over it — so in any real deployment, set the six secrets below as container/platform environment variables and don't ship a `.env` file in the image at all (the Dockerfile doesn't copy one).
- **Never bake API keys into the image.** `backend/Dockerfile` does not `COPY .env`; don't add it. If you need to double check an image doesn't contain a stray `.env`, `docker run --rm <image> find / -name '.env'` should come back empty.

Secrets/config to set at deploy time (see `.env.example` for the full list with descriptions):

| Variable | Required for | Notes |
|---|---|---|
| `BREEZE_API_KEY` / `BREEZE_API_SECRET` | any live market data | static app credentials from ICICI Direct |
| `BREEZE_SESSION_TOKEN` | any live market data | **expires at midnight IST every day — see §5, this is the one recurring operational task** |
| `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | the 3 LLM-backed agents | missing one degrades that agent's provider only |
| `NEWSAPI_KEY` | News & Sentiment agent | |
| `DATABASE_URL` | persistence | override only if moving off the default SQLite file path |
| `CORS_ALLOWED_ORIGINS` | frontend reachability | comma-separated exact origins, e.g. `https://committee.example.com` — **required** once the frontend isn't on localhost, see §4 |

If you're on a platform with a real secrets manager (AWS Secrets Manager, GCP Secret Manager, Doppler, etc.), inject these as env vars at container start rather than checking any of them into compose files or CI config.

## 3. Pre-build data step (one-time, local)

Two data directories are git-ignored (`data/models/*`, `data/historical/*` — see `.gitignore`) because they're locally-generated, not source:

- `data/models/` — the Forecasting agent's trained LightGBM model. **Optional**: `agents/forecasting.py` degrades gracefully (returns no forecast) if this is missing, it just means one fewer committee voice. Generate it with:
  ```
  python scripts/train_forecasting_model.py
  ```
- `data/historical/` — Replay Mode's OHLCV cache. **Self-healing**: `market_data/prices.py`'s `fetch_ohlcv` populates this cache automatically on any live Breeze pull, and `load_cached_ohlcv` (replay path) will fetch-and-cache on first use if a symbol's file doesn't exist yet. You only need this pre-populated if you want Replay Mode to work with zero live Breeze calls (e.g. a demo running with expired/no credentials).

`backend/Dockerfile` `COPY`s both directories into the image, so run the training script (and/or a live session to warm the cache) **before** `docker build`, from whatever machine has working Breeze credentials. If you'd rather not bake locally-generated data into the image at all, drop those two `COPY` lines and mount `data/models`/`data/historical` as volumes instead — trades cache freshness for a smaller, more reproducible image.

## 4. Local / single-host deployment (docker-compose)

```
cp .env.example .env   # then fill in real values -- see §2. docker compose's
                        # env_file: entry requires this file to exist at all,
                        # even if some values are still blank.
docker compose build
docker compose up -d
```

- Backend: `http://localhost:8001` (health check at `/health`).
- Frontend: `http://localhost:8080`.
- Trade history persists across `docker compose down` / `up` via the `committee-db` named volume (only `down -v` wipes it).

The frontend image is built once and configured at **container start**, not build time: `frontend/docker-entrypoint.sh` regenerates `/env-config.js` from the `API_BASE_URL` env var every time the container starts (nginx's base image runs anything executable in `/docker-entrypoint.d/` automatically). This means the same built frontend image can point at any backend — local, staging, prod — via one env var, with no rebuild. See `frontend/src/api.ts` for the client-side read of `window.__ENV__.API_BASE_URL`.

In the shipped `docker-compose.yml`, `API_BASE_URL` is set to `http://127.0.0.1:8001` — this works specifically because it's read by the **browser**, not the container (the browser executes `env-config.js`), and the backend's port is also published to the host. If frontend and backend end up on different hosts (§6), point `API_BASE_URL` at the backend's real public URL instead.

## 5. Daily operational runbook: refreshing the Breeze session token

This is not optional maintenance — it's a hard SEBI requirement, not a bug in this system. `BREEZE_SESSION_TOKEN` expires at midnight IST every trading day and there is no automated refresh path (`config.py`'s own comment: "SEBI requires the user to grab [it] via a manual browser login every trading day"). Whoever operates this deployment needs to, every trading morning before market open:

1. Log in at `https://api.icicidirect.com/apiuser/home` (View Apps) and grab the fresh `api_session` value from the redirect URL.
2. Update the deployed `BREEZE_SESSION_TOKEN` env var (host env var, platform secret, or `.env` + `docker compose up -d` locally — `Settings` is a module-level singleton read once at import, so this always requires a container restart, not just an env change).
3. Restart the backend container: `docker compose restart backend` (or your platform's equivalent). Confirm via `/health` and check backend logs for a successful Breeze session on the next cycle.

If this step is missed, live market-data fetches fail; `fetch_ohlcv` (§3) falls back to the last cached bars, so the system keeps running but on stale data rather than erroring loudly — worth an alert/dashboard check, not just relying on it to fail visibly.

## 6. Splitting frontend and backend across separate hosts / a managed platform

Nothing above requires compose specifically — the same two images work on ECS, Cloud Run, App Service, a bare VM pair, etc. What changes:

- **CORS**: set `CORS_ALLOWED_ORIGINS` on the backend to the frontend's real origin(s) (comma-separated, exact match — see `api/main.py`'s `CORSMiddleware` setup). Without this, the browser blocks the frontend's API calls once it's not on `localhost`.
- **`API_BASE_URL`**: set it to the backend's public URL when starting the frontend container (§4) — same mechanism, just a different value.
- **TLS**: neither Dockerfile terminates TLS. Put both services behind whatever the platform provides (an ALB/Cloud Load Balancer, or a reverse proxy like Caddy/Traefik in front of the compose stack) rather than adding certs into the frontend nginx config directly — keeps the images portable across platforms.
- **Backend replica count stays at 1** regardless of platform (§1) — most managed platforms default to autoscaling; explicitly pin this service to a single instance/task.

## 7. Rollback / verification checklist

- `GET /health` on the backend returns `{"status": "ok"}`.
- `GET /portfolio` returns the expected cash/positions (compare against the previous deploy if this is a redeploy, not a fresh environment — a mismatch here after a restart likely means the container recreated without the `committee-db` volume attached).
- Frontend loads and its network tab shows calls going to the intended `API_BASE_URL`, not a stale cached one (double-check `/env-config.js` isn't being cached by a CDN in front of nginx — see the `Cache-Control: no-store` rule already set in `frontend/nginx.conf` for this exact reason).
- If a redeploy needs to be undone: redeploy the previous image tag for whichever service regressed; the SQLite volume is untouched by an image swap, so trade history survives.

## 8. CI/CD pipeline (the only sanctioned path to a published image)

`.github/workflows/ci-cd.yml`, three jobs:

1. **`backend-tests`** — installs `requirements.txt`, runs `pytest backend/committee/tests`. Runs on every push and every PR into `main`.
2. **`frontend-build`** — `npm ci`, then `npm run build` (`tsc && vite build`, so a type error fails the build the same as a broken bundle). Runs on every push and every PR.
3. **`docker-publish`** — `needs: [backend-tests, frontend-build]`, and additionally gated with `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`. A PR from a branch (or a fork) runs the two test jobs and stops — it can never publish an image, even if someone adds docker credentials to a PR run. Only a merge into `main` that passes both jobs builds and pushes.

Published to GHCR (`ghcr.io/<owner>/<repo>-backend`, `ghcr.io/<owner>/<repo>-frontend`), tagged `latest` and the commit SHA, using the workflow's own `GITHUB_TOKEN` — no extra registry secret to provision or leak. Pull one down locally with:
```
docker pull ghcr.io/<owner>/<repo>-backend:<sha-or-latest>
```

**Practical workflow this enforces**: make changes locally → `docker compose build && up` to sanity-check the containers actually run → open a PR → CI runs the same two test jobs the merge will need anyway → merge → CI builds and publishes the images. There's no step in between where a manually-built image reaches the registry other than through this sequence.

**Known gap**: CI checks out a fresh clone, so `data/models/` and `data/historical/` are just their `.gitkeep` placeholders when the `docker-publish` job builds `backend/Dockerfile` (both are git-ignored — see §3). The published image is therefore always the "degraded but functional" case from §3: no trained Forecasting-agent model, empty Replay Mode cache that self-heals on first live Breeze pull. If you need CI-built images to ship a trained model, that means fetching it from external storage (a release asset, S3, etc.) as a build step — not implemented here, since there's currently nowhere for CI to pull it from.
