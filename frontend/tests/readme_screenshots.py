"""Capture the real UI in dark mode with synthetic data; never contacts a live API.

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
    sensor_job = name in {"device_telemetry", "temperature_alerts"}
    job.update(id=i + 1, name=name, description=description, live_state=state,
               target_name="edge" if sensor_job else None,
               tags=["sensors" if sensor_job else "commerce"])
    job["latest_run"].update(id=i + 1, job=name, state=state, started_at=started)
    if state == "finished":
        job.update(job_type="batch", schedule={"mode": "cron", "enabled": True, "cron_expr": "0 * * * *"})
        job["latest_run"]["ended_at"] = "2026-09-16T11:02:00Z"
        job["checkpoint_age_ms"] = None
    fixtures["/api/jobs"].append(job)
fixtures["/api/targets"][0].update(job_count=3, slots_available=10)
fixtures["/api/targets"][1].update(name="edge", description="Sensor pipelines",
    job_count=2, slots_total=8, slots_available=6,
    flink_rest_url="http://edge:8081", gateway_url="http://edge:8083")
fixtures["/api/cluster"].update(slots_total=20, slots_available=16,
    targets_total=2, targets_reachable=2)
fixtures["/api/system/version"] = {
    "console": {"revision": None, "update_available": False},
    "flink": {"revision": None, "update_available": False},
    "update_check": {"enabled": False}, "latest": None,
}


# The job page: one job's run history, with saved state to show the timeline.
SP_NEW = "file:///flink-savepoints/savepoint-7c41aa-5e2f0b9d8c11"
SP_OLD = "file:///flink-savepoints/savepoint-3b90de-0a9c4e2d7f63"
ORDERS_SQL = """-- Validated orders only; the warehouse rejects rows without a customer.
INSERT INTO warehouse_orders
SELECT
  order_id,
  customer_id,
  CAST(amount AS DECIMAL(10, 2)) AS amount,
  status,
  ts AS ordered_at
FROM orders
WHERE customer_id IS NOT NULL
  AND status <> 'test';"""
detail = deepcopy(fixtures["/api/jobs"][0])
run = detail["latest_run"]
run.update(id=14, started_at="2026-09-16T08:14:00Z", restored_from=SP_NEW, flink_job_id="3f9d0c1e8a7b4c25")
detail.update(sql_text=ORDERS_SQL, catalog_refs=["orders", "warehouse_orders"], version=3,
              checkpoint_age_ms=4000,
              restore_point={"path": SP_NEW, "kind": "savepoint", "taken_at": "2026-09-16T08:13:00Z"})
fixtures["/api/jobs/orders_to_warehouse"] = detail
fixtures["/api/jobs/orders_to_warehouse/runs"] = [
    dict(run),
    dict(run, id=13, state="canceled", started_at="2026-09-16T02:07:00Z", ended_at="2026-09-16T08:13:00Z",
         savepoint_path=SP_NEW, restored_from="file:///flink-state/checkpoints/3f9d/chk-1284", flink_job_id=None),
    dict(run, id=12, state="failed", started_at="2026-09-15T20:00:00Z", ended_at="2026-09-16T02:06:00Z",
         restarts=3, restored_from=SP_OLD, flink_job_id=None,
         error_summary="Kafka broker unreachable: broker:9092 timed out after 60s"),
    dict(run, id=11, state="canceled", started_at="2026-09-15T09:00:00Z", ended_at="2026-09-15T19:58:00Z",
         savepoint_path=SP_OLD, restored_from=None, flink_job_id=None),
]
fixtures["/api/jobs/orders_to_warehouse/versions"] = [
    {"version": 3, "note": "Drop test orders", "created_at": "2026-09-15T08:40:00Z", "created_by": "operator"},
    {"version": 2, "note": "Cast amount for the warehouse", "created_at": "2026-09-10T14:02:00Z", "created_by": "operator"},
    {"version": 1, "note": "Created", "created_at": "2026-09-02T09:15:00Z", "created_by": "operator"},
]
fixtures["/api/jobs/orders_to_warehouse/script"] = {"statements": [ORDERS_SQL]}
fixtures["/api/jobs/validate"] = {"ok": True, "warnings": []}

# Catalog entries the editor offers, with columns to pick from.
def entry(i, name, connector, description, columns, key, kind, label, read_by=(), written_by=()):
    return dict(fixtures["/api/catalog"][0], id=100 + i, name=name, kind="table", connector=connector,
                description=description, options={}, version=1,
                columns=[{"name": n, "type": t} for n, t in columns],
                used_by=list(read_by) + list(written_by), read_by=list(read_by), written_by=list(written_by),
                resource={"key": key, "kind": kind, "label": label})
fixtures["/api/catalog"] = [
    entry(1, "orders", "kafka", "Orders as the shop publishes them.",
          [("order_id", "STRING"), ("customer_id", "STRING"), ("amount", "DOUBLE"), ("status", "STRING"), ("ts", "TIMESTAMP(3)")],
          "kafka:broker:9092/orders", "kafka topic", "orders", read_by=["orders_to_warehouse", "hourly_order_totals"]),
    entry(2, "warehouse_orders", "jdbc", "The analytics warehouse's orders table.",
          [("order_id", "STRING"), ("customer_id", "STRING"), ("amount", "DECIMAL(10, 2)"), ("status", "STRING"), ("ordered_at", "TIMESTAMP(3)")],
          "jdbc:warehouse/orders", "database table", "warehouse.orders", written_by=["orders_to_warehouse"]),
    entry(3, "device_readings", "kafka", "Raw readings from the sensor gateway.",
          [("device_id", "STRING"), ("temperature", "DOUBLE"), ("ts", "TIMESTAMP(3)")],
          "kafka:broker:9092/device-readings", "kafka topic", "device-readings",
          read_by=["device_telemetry", "temperature_alerts"]),
]

# The pipeline map, drawn from the same example jobs as the list.
def job_node(name, state, cluster):
    return {"id": f"job:{name}", "type": "job", "label": name, "state": state, "cluster": cluster}
def topic(key, label, kind, entries):
    return {"id": f"res:{key}", "type": "resource", "kind": kind, "label": label, "key": key, "entries": entries}
fixtures["/api/pipeline"] = {
    "nodes": [
        {"id": "ext:1", "type": "external", "label": "shop", "direction": "produces", "note": None,
         "endpoint_id": 1, "resource": "kafka:broker:9092/orders"},
        {"id": "ext:2", "type": "external", "label": "sensor gateway", "direction": "produces", "note": None,
         "endpoint_id": 2, "resource": "kafka:broker:9092/device-readings"},
        topic("kafka:broker:9092/orders", "orders", "kafka topic", ["orders"]),
        topic("kafka:broker:9092/inventory", "inventory", "kafka topic", ["inventory"]),
        topic("kafka:broker:9092/device-readings", "device-readings", "kafka topic", ["device_readings"]),
        topic("jdbc:warehouse/orders", "warehouse.orders", "database table", ["warehouse_orders"]),
        topic("jdbc:warehouse/order_totals", "warehouse.order_totals", "database table", ["order_totals"]),
        topic("jdbc:warehouse/stock", "warehouse.stock", "database table", ["stock_levels"]),
        topic("couchdb:telemetry", "telemetry", "couchdb database", ["telemetry"]),
        topic("kafka:broker:9092/alerts", "alerts", "kafka topic", ["alerts"]),
        job_node("orders_to_warehouse", "running", "default"),
        job_node("hourly_order_totals", "finished", "default"),
        job_node("inventory_changes", "running", "default"),
        job_node("device_telemetry", "running", "edge"),
        job_node("temperature_alerts", "running", "edge"),
    ],
    "edges": [
        {"from": "ext:1", "to": "res:kafka:broker:9092/orders"},
        {"from": "res:kafka:broker:9092/orders", "to": "job:orders_to_warehouse"},
        {"from": "job:orders_to_warehouse", "to": "res:jdbc:warehouse/orders"},
        {"from": "res:kafka:broker:9092/orders", "to": "job:hourly_order_totals"},
        {"from": "job:hourly_order_totals", "to": "res:jdbc:warehouse/order_totals"},
        {"from": "res:kafka:broker:9092/inventory", "to": "job:inventory_changes"},
        {"from": "job:inventory_changes", "to": "res:jdbc:warehouse/stock"},
        {"from": "ext:2", "to": "res:kafka:broker:9092/device-readings"},
        {"from": "res:kafka:broker:9092/device-readings", "to": "job:device_telemetry"},
        {"from": "job:device_telemetry", "to": "res:couchdb:telemetry"},
        {"from": "res:kafka:broker:9092/device-readings", "to": "job:temperature_alerts"},
        {"from": "job:temperature_alerts", "to": "res:kafka:broker:9092/alerts"},
    ],
    "unused": [],
}

# (page, file, what proves it rendered, viewport height). Full-page captures,
# except the map, whose page is mostly empty below the drawing.
SHOTS = [
    ("/jobs", "jobs.png", lambda p: p.get_by_role("link", name="orders_to_warehouse", exact=True), 900, True),
    ("/jobs/orders_to_warehouse", "job.png", lambda p: p.get_by_text("state saved as").first, 900, True),
    ("/pipeline", "pipeline.png", lambda p: p.get_by_role("button", name="job orders_to_warehouse"), 640, False),
    ("/jobs/orders_to_warehouse/edit", "editor.png", lambda p: p.get_by_text("Compiles", exact=True), 900, True),
]

with sync_playwright() as pw:
    browser = pw.chromium.launch(args=["--no-sandbox"])
    for path, name, ready, height, full in SHOTS:
        page = browser.new_page(viewport={"width": 1440, "height": height}, device_scale_factor=1,
                                color_scheme="dark", timezone_id="UTC", locale="en-US")
        page.clock.set_fixed_time("2026-09-16T12:00:00Z")
        page.add_init_script("localStorage.setItem('mars.theme', 'dark')")
        errors = []
        missing = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def intercept(route):
            url = urlsplit(route.request.url)
            path = unquote(url.path)
            if path.startswith("/api/"):
                if path not in fixtures:
                    missing.append(path)
                route.fulfill(json=fixtures.get(path, []))
            elif url.netloc == urlsplit(base).netloc:
                route.continue_()
            else:
                route.abort()

        page.route("**/*", intercept)
        page.goto(base + path, wait_until="networkidle")
        expect(ready(page)).to_be_visible()
        expect(page.locator("html")).to_have_class("dark")
        page.evaluate("document.fonts.ready")
        assert not missing, f"Missing screenshot fixtures on {path}: {missing}"
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), f"Horizontal overflow on {path}"
        page.screenshot(path=str(out / name), full_page=full)
        assert not errors, errors
        page.close()
        print(f"Saved docs/images/{name}")
    browser.close()
print("README images refreshed in dark mode using synthetic fixtures.")
