# Demo UI (added; no existing engine file was modified)

React + Vite + Recharts dashboard served by a small standard-library Python server (`server.py`) that calls the
real engine. Three tabs: **Agent run** (animated, stage-by-stage decision with highlighted message and live log),
**Statistics** (the engine run over every thread), **Playbook** (rules, categories, suppliers, amendments, precedents).

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node.js 18+ (npm is included).
From the repository root, create and activate the Python environment, build the UI, and start the server:

    uv sync --locked
    .venv\Scripts\Activate.ps1       # Windows PowerShell
    npm --prefix ui/web ci
    npm --prefix ui/web run build
    python ui/server.py --root dataset

On macOS/Linux, use `source .venv/bin/activate` instead of the Windows activation command. The app starts at
http://127.0.0.1:8000 and loads its playbook and example threads from `dataset/`.

Alternatively, after building the UI, run the server without activating the environment:

    uv run python ui/server.py --root dataset

## Change the UI (needs Node 18+)
    cd ui/web && npm install
    npm run dev                         # hot reload on :5173, proxies /api to :8000 (run server.py too)
    npm run build                       # writes ui/dist

## Deploy (any Docker host: Render, Railway, Fly.io, Hugging Face "Docker" Space)
1. Make sure `dataset/` is in the repo you deploy (it becomes public if the site is public).
2. Point the host at `ui/Dockerfile` (build context = repo root). It builds the UI and listens on `$PORT`.
3. The server has no login; add basic auth at the gateway if the page should not be public.
