"""Capture the real UI with synthetic data only; never contacts a live API.

Run against a local Vite server: python tests/readme_screenshots.py
"""
import os
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.sync_api import sync_playwright, expect
from fixtures import fixtures as make_fixtures

base = os.getenv("UI_BASE_URL", "http://127.0.0.1:5173").rstrip("/")
out = Path(__file__).resolve().parents[2] / "docs/images"
out.mkdir(parents=True, exist_ok=True)
fixtures = make_fixtures()
base_job = fixtures["/api/jobs"][0]
examples = [
    ("orders_to_warehouse", "Stream validated orders into the analytics warehouse.", "running", "2026-09-16T08:14:00Z"),
    ("device_telemetry", "Normalize device readings and route them to storage.", "running", "2026-09-16T09:05:00Z"),
    ("temperature_alerts", "Flag readings above the configured temperature threshold.", "running", "2026-09-16T10:32:00Z"),
    ("hourly_order_totals", "Aggregate order volume and revenue for reporting.", "finished", "2026-09-16T11:00:00Z"),
    ("inventory_changes", "Track stock changes across product locations.", "running", "2026-09-16T11:18:00Z"),
]
fixtures["/api/jobs"] = []
for i, (name, description, state, started) in enumerate(examples):
    job = deepcopy(base_job)
    job.update(id=i + 1, name=name, description=description)
    job["latest_run"].update(id=i + 1, job=name, state=state, started_at=started)
    if state == "finished":
        job.update(job_type="batch", schedule={"mode": "cron", "enabled": True, "cron_expr": "0 * * * *"})
        job["latest_run"]["ended_at"] = "2026-09-16T11:02:00Z"
    fixtures["/api/jobs"].append(job)
fixtures["/api/targets"][0].update(job_count=5, slots_available=8)
fixtures["/api/cluster"].update(slots_available=8)

with sync_playwright() as pw:
    browser = pw.chromium.launch(args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 760}, device_scale_factor=1)
    page.clock.set_fixed_time("2026-09-16T12:00:00Z")
    page.add_init_script("localStorage.setItem('mars.theme', 'light')")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def intercept(route):
        url = urlsplit(route.request.url)
        path = unquote(url.path)
        if path.startswith("/api/"):
            route.fulfill(json=fixtures.get(path, []))
        elif url.netloc == urlsplit(base).netloc:
            route.continue_()
        else:
            route.abort()

    page.route("**/*", intercept)
    page.goto(base + "/jobs", wait_until="networkidle")
    expect(page.get_by_role("link", name="orders_to_warehouse", exact=True)).to_be_visible()
    page.screenshot(path=str(out / "jobs.png"))
    assert not errors, errors
    browser.close()
print("Saved docs/images/jobs.png using synthetic fixtures.")
