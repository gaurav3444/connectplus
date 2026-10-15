# CONNECT Plus

Digital navigation and referral platform for culturally and linguistically
diverse (CALD) seniors. Three projects in one repo, each with its own README:

| Folder | What it is | Run with |
|---|---|---|
| [`connect-plus-app/`](connect-plus-app) | Next.js web app: the senior and helper screens | `npm install && npm run dev` (port 3000) |
| [`connectplus-llm/`](connectplus-llm) | Answer service: understands the question, writes the answer | `uvicorn demo.server:app --port 8000` |
| [`connectplus-rag/`](connectplus-rag) | Trusted-source index: retrieval, verification, browse menu | imported by `connectplus-llm` as a Python package |

## Run everything

```bash
npm start
```

Needs Node 20.11+ and Python 3.11+. The first run installs the app's packages
and a Python environment for the LLM and RAG (PyTorch included, a few GB),
and creates each project's `.env` from its template. Then it starts the
answer service on :8000 and the app on http://localhost:3000; Ctrl+C stops
both. With `DATABASE_URL` in `connectplus-rag/.env` and `GEMINI_API_KEY` in
`connectplus-llm/.env` answers are real; without them the LLM runs its offline
demo mode.

How they connect: the app sends a question to `connectplus-llm`, which calls
`connectplus-rag` in the same process to retrieve sources and verify the
answer. The app reads the Browse menu straight from the `browse_resources`
table that `connectplus-rag` builds in Supabase.

Full commit history from the original three repositories is kept here, with
each project's files in its own folder from the first commit:
[connect-plus-app](https://github.com/gaurav3444/connect-plus-app) (`dev`),
[connectplus-llm](https://github.com/gaurav3444/connectplus-llm) (`main`),
[-connectplus-rag](https://github.com/gaurav3444/-connectplus-rag) (`rag-merge`).
