# Development

Use Python 3.12 and Node.js 22. Start a Flink cluster only when exercising submission;
unit tests and the fixture-backed browser checks do not need one.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt pytest pytest-asyncio
cd backend
MARS_DATA_DIR=/tmp/mars-dev uvicorn app.main:app --reload --port 8080
```

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Vite serves the UI on `localhost:5173` and proxies API requests to port 8080.
For a local backend connected to Docker, set `MARS_FLINK_REST_URL` and
`MARS_SQL_GATEWAY_URL` to endpoints accessible from that process.

## Checks

```bash
cd backend
python -m pytest tests --ignore=tests/integration
```

```bash
cd frontend
npm ci
npm run build
npm audit
```

Browser checks intercept API traffic with synthetic fixtures. With Vite running:

```bash
pip install playwright==1.49.0
playwright install chromium
cd frontend
python tests/browser_smoke.py
```

Set `UI_SCREENSHOTS=/tmp/mars-ui-screenshots` to also check both themes across
four viewport widths. Set `UI_BASE_URL` for a different frontend address.
Run `python tests/readme_screenshots.py` to refresh the README image from sample data.
Never use screenshots of a live installation for public documentation.

Integration tests in `backend/tests/integration/` execute real Flink jobs and require
explicit endpoint configuration. Run them only against an isolated test stack.
`scripts/clean-room-test.sh` tests installation inside a disposable Docker daemon;
it needs privileged Docker access and downloads/builds the full stack.

Before sharing changes, scan both the files and Git history with a secret scanner,
and run dependency audits. `.gitignore` does not remove files already committed.
