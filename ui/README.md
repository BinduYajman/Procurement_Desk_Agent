# Demo UI (added; no existing engine file was modified)

React + Vite + Recharts dashboard served by a small standard-library Python server (`server.py`) that calls the
real engine. Three tabs: **Agent run** (animated, stage-by-stage decision with highlighted message and live log),
**Statistics** (the engine run over every thread), **Playbook** (rules, categories, suppliers, amendments, precedents).

## Run locally (no Node needed: the built UI is in ui/dist)
    # put the organisers' dataset/ folder in the repo root (playbook/ + threads.csv), then:
    python ui/server.py --root .        # open http://127.0.0.1:8000

## Change the UI (needs Node 18+)
    cd ui/web && npm install
    npm run dev                         # hot reload on :5173, proxies /api to :8000 (run server.py too)
    npm run build                       # writes ui/dist

## Deploy (any Docker host: Render, Railway, Fly.io, Hugging Face "Docker" Space)
1. Make sure `dataset/` is in the repo you deploy (it becomes public if the site is public).
2. Point the host at `ui/Dockerfile` (build context = repo root). It builds the UI and listens on `$PORT`.
3. The server has no login; add basic auth at the gateway if the page should not be public.
