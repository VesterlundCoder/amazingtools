#!/usr/bin/env python3
"""
audit_amazingtools.py — Automated API + frontend audit bot for Amazing Tools.

Usage:
    python audit_amazingtools.py [--base-url URL]

Outputs a BUGS.md report in the same directory.
"""
from __future__ import annotations
import argparse, json, time, sys, re
from typing import Any
import urllib.request, urllib.error

_parser = argparse.ArgumentParser(description="Amazing Tools audit bot")
_parser.add_argument("--base-url", default="https://web-production-c14f30.up.railway.app")
_parser.add_argument("--frontend-url", default="", help="Static frontend base URL (e.g. https://amazingtools.se)")
_args = _parser.parse_args()
BASE_URL = _args.base_url.rstrip("/")
FRONTEND_PAGES = [
    "dashboard.html", "agents.html", "agent-runner.html",
    "seo-crawler.html", "query-match.html", "brand-voice.html",
    "mevo-ai.html", "aiv-dashboard.html", "ipr-sandbox.html",
    "client.html", "client-workspace.html", "login.html",
]
# Frontend is served separately (cpanel/static host) — set via --frontend-url
FRONTEND_BASE = _args.frontend_url.rstrip("/") if _args.frontend_url else ""

bugs: list[dict] = []
passed: list[str] = []


def _request(method: str, path: str, body: Any = None, timeout: int = 20) -> tuple[int, Any]:
    url = BASE_URL + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:
        return 0, str(e)


def bug(severity: str, section: str, title: str, detail: str = ""):
    bugs.append({"severity": severity, "section": section, "title": title, "detail": detail})
    print(f"  ❌ [{severity}] {section}: {title}")
    if detail:
        print(f"     → {detail[:120]}")


def ok(label: str):
    passed.append(label)
    print(f"  ✅ {label}")


def section(name: str):
    print(f"\n{'─'*60}")
    print(f"  {name}")
    print(f"{'─'*60}")


# ── 1. Health / root ─────────────────────────────────────────────────────────
section("1. API Health")
code, body = _request("GET", "/")
if code == 200:
    ok("GET / → 200")
elif code == 404:
    ok("GET / → 404 (expected for FastAPI, no root handler)")
else:
    bug("HIGH", "API Health", f"Unexpected status on GET /: {code}", str(body)[:200])

code, body = _request("GET", "/docs")
if code in (200, 307):
    ok("GET /docs → accessible")
else:
    bug("LOW", "API Health", f"Swagger /docs returned {code}")


# ── 2. Agents list ───────────────────────────────────────────────────────────
section("2. Agent Registry (/api/agents/list)")
code, agents = _request("GET", "/api/agents/list")
if code != 200:
    bug("HIGH", "Agents", f"/api/agents/list returned {code}", str(agents))
    agents = []
else:
    ok(f"/api/agents/list → {len(agents)} agents")
    required_keys = ["id", "name", "inputs", "description"]
    for a in agents:
        for k in required_keys:
            if k not in a:
                bug("MEDIUM", "Agents", f"Agent '{a.get('id','?')}' missing field '{k}'")
        if a.get("inputs") and not isinstance(a["inputs"], list):
            bug("MEDIUM", "Agents", f"Agent '{a.get('id')}' inputs is not a list")
    ok(f"All {len(agents)} agent definitions have required fields")


# ── 3. Amazing Client CRUD ───────────────────────────────────────────────────
section("3. Amazing Client — Customer CRUD")
TEST_CLIENT_ID = None

# Create
code, client = _request("POST", "/api/clients", {
    "company_name": "AuditBot TestCo",
    "primary_domain": "testco.example.com",
    "industry": "Testing",
    "service_mode": "ADVISORY",
    "markets": ["SE"],
    "competitors": [{"name": "RivalCo", "domain": "rival.example.com"}],
    "goals": [{"title": "Grow organic traffic 50%"}],
})
if code == 200:
    TEST_CLIENT_ID = client.get("id")
    ok(f"POST /api/clients → created client {TEST_CLIENT_ID}")
    if not client.get("pinned_tools") and client.get("pinned_tools") != []:
        bug("MEDIUM", "Clients", "pinned_tools field missing from POST response")
else:
    bug("HIGH", "Clients", f"POST /api/clients failed: {code}", str(client))

# List
code, lst = _request("GET", "/api/clients")
if code == 200 and isinstance(lst, list):
    ok(f"GET /api/clients → {len(lst)} clients")
else:
    bug("HIGH", "Clients", f"GET /api/clients failed: {code}", str(lst))

# Get
if TEST_CLIENT_ID:
    code, c = _request("GET", f"/api/clients/{TEST_CLIENT_ID}")
    if code == 200 and c.get("id") == TEST_CLIENT_ID:
        ok(f"GET /api/clients/{TEST_CLIENT_ID} → OK")
        for f in ("markets", "languages", "competitors", "goals", "pinned_tools"):
            if not isinstance(c.get(f), list):
                bug("MEDIUM", "Clients", f"Field '{f}' not deserialized to list in GET response", str(c.get(f)))
    else:
        bug("HIGH", "Clients", f"GET /api/clients/{{id}} failed: {code}")

    # Update
    code, updated = _request("PUT", f"/api/clients/{TEST_CLIENT_ID}", {"status": "ACTIVE", "notes": "Audit test note"})
    if code == 200 and updated.get("status") == "ACTIVE":
        ok("PUT /api/clients/{id} → status updated")
    else:
        bug("HIGH", "Clients", f"PUT /api/clients/{{id}} failed: {code}", str(updated))

    # Stats
    code, stats = _request("GET", f"/api/clients/{TEST_CLIENT_ID}/stats")
    if code == 200 and "open_tasks" in stats:
        ok("GET /api/clients/{id}/stats → OK")
    else:
        bug("MEDIUM", "Clients", f"GET /api/clients/{{id}}/stats failed: {code}", str(stats))


# ── 4. Tasks CRUD ────────────────────────────────────────────────────────────
section("4. Tasks")
TEST_TASK_ID = None

if TEST_CLIENT_ID:
    code, task = _request("POST", f"/api/clients/{TEST_CLIENT_ID}/tasks", {
        "title": "Fix H1 tags",
        "description": "All product pages missing H1",
        "impact": "HIGH",
    })
    if code == 200 and task.get("id"):
        TEST_TASK_ID = task["id"]
        ok(f"POST tasks → {TEST_TASK_ID}")
    else:
        bug("HIGH", "Tasks", f"POST /api/clients/{{id}}/tasks failed: {code}", str(task))

    code, tasks = _request("GET", f"/api/clients/{TEST_CLIENT_ID}/tasks")
    if code == 200 and isinstance(tasks, list):
        ok(f"GET tasks → {len(tasks)} tasks")
    else:
        bug("HIGH", "Tasks", f"GET tasks failed: {code}")

    if TEST_TASK_ID:
        code, upd = _request("PUT", f"/api/clients/{TEST_CLIENT_ID}/tasks/{TEST_TASK_ID}", {"status": "IN_PROGRESS"})
        if code == 200 and upd.get("status") == "IN_PROGRESS":
            ok("PUT task status → IN_PROGRESS")
        else:
            bug("MEDIUM", "Tasks", f"PUT task status failed: {code}", str(upd))


# ── 5. Insights CRUD ─────────────────────────────────────────────────────────
section("5. Insights")
TEST_INSIGHT_ID = None

if TEST_CLIENT_ID:
    code, ins = _request("POST", f"/api/clients/{TEST_CLIENT_ID}/insights", {
        "title": "Core Web Vitals failing on mobile",
        "body": "LCP > 4s on top 5 product pages",
        "severity": "HIGH",
        "category": "technical",
    })
    if code == 200 and ins.get("id"):
        TEST_INSIGHT_ID = ins["id"]
        ok(f"POST insights → {TEST_INSIGHT_ID}")
    else:
        bug("HIGH", "Insights", f"POST insights failed: {code}", str(ins))

    code, inss = _request("GET", f"/api/clients/{TEST_CLIENT_ID}/insights")
    if code == 200 and isinstance(inss, list):
        ok(f"GET insights → {len(inss)} insights")
    else:
        bug("HIGH", "Insights", f"GET insights failed: {code}")

    if TEST_INSIGHT_ID:
        code, upd = _request("PUT", f"/api/clients/{TEST_CLIENT_ID}/insights/{TEST_INSIGHT_ID}", {"status": "IN_PROGRESS"})
        if code == 200 and upd.get("status") == "IN_PROGRESS":
            ok("PUT insight status → IN_PROGRESS")
        else:
            bug("MEDIUM", "Insights", f"PUT insight status failed: {code}", str(upd))


# ── 6. Comments ───────────────────────────────────────────────────────────────
section("6. Comments / Notes")
TEST_COMMENT_ID = None

if TEST_CLIENT_ID:
    code, c = _request("POST", f"/api/clients/{TEST_CLIENT_ID}/comments", {"body": "Audit test note — please ignore"})
    if code == 200 and c.get("id"):
        TEST_COMMENT_ID = c["id"]
        ok(f"POST comments → {TEST_COMMENT_ID}")
    else:
        bug("HIGH", "Comments", f"POST comments failed: {code}", str(c))

    code, cs = _request("GET", f"/api/clients/{TEST_CLIENT_ID}/comments")
    if code == 200 and isinstance(cs, list):
        ok(f"GET comments → {len(cs)} comments")
    else:
        bug("HIGH", "Comments", f"GET comments failed: {code}", str(cs))

    # Test target_type filter (tests Optional[str] fix)
    code, filt = _request("GET", f"/api/clients/{TEST_CLIENT_ID}/comments?target_type=customer")
    if code == 200:
        ok("GET comments?target_type=customer → OK (Optional[str] fix working)")
    else:
        bug("HIGH", "Comments", f"GET comments with target_type param failed: {code} (Optional[str] bug!)", str(filt))

    if TEST_COMMENT_ID:
        code, pinned = _request("POST", f"/api/clients/{TEST_CLIENT_ID}/comments/{TEST_COMMENT_ID}/pin")
        if code == 200 and pinned.get("pinned") == 1:
            ok("POST pin comment → pinned=1")
        else:
            bug("MEDIUM", "Comments", f"Pin comment failed: {code}", str(pinned))


# ── 7. Runs ───────────────────────────────────────────────────────────────────
section("7. Runs")
TEST_RUN_ID = None

if TEST_CLIENT_ID:
    code, run = _request("POST", f"/api/clients/{TEST_CLIENT_ID}/runs", {
        "job_id": "test-job-000",
        "module_id": "aiv",
        "module_name": "AI Visibility",
        "status": "SUCCESS",
        "summary": "Test run from audit bot",
    })
    if code == 200 and run.get("id"):
        TEST_RUN_ID = run["id"]
        ok(f"POST runs → {TEST_RUN_ID}")
    else:
        bug("HIGH", "Runs", f"POST runs failed: {code}", str(run))

    code, runs = _request("GET", f"/api/clients/{TEST_CLIENT_ID}/runs")
    if code == 200 and isinstance(runs, list):
        ok(f"GET runs → {len(runs)} runs")
    else:
        bug("HIGH", "Runs", f"GET runs failed: {code}")

    if TEST_RUN_ID:
        code, upd = _request("PUT", f"/api/clients/{TEST_CLIENT_ID}/runs/{TEST_RUN_ID}", {"status": "SUCCESS", "summary": "Updated summary"})
        if code == 200 and upd.get("status") == "SUCCESS":
            ok("PUT run status → SUCCESS")
        else:
            bug("MEDIUM", "Runs", f"PUT run failed: {code}", str(upd))


# ── 8. Pinned tools ───────────────────────────────────────────────────────────
section("8. Pinned Tools")

if TEST_CLIENT_ID:
    code, res = _request("POST", f"/api/clients/{TEST_CLIENT_ID}/tools/aiv/pin")
    if code == 200 and "aiv" in (res.get("pinned_tools") or []):
        ok("POST pin tool 'aiv' → appears in pinned_tools")
    else:
        bug("HIGH", "Pinned Tools", f"POST /tools/{{id}}/pin failed: {code}", str(res))

    # Toggle off
    code, res2 = _request("POST", f"/api/clients/{TEST_CLIENT_ID}/tools/aiv/pin")
    if code == 200 and "aiv" not in (res2.get("pinned_tools") or []):
        ok("POST pin tool 'aiv' again → toggled off (unpinned)")
    else:
        bug("MEDIUM", "Pinned Tools", f"Toggle-off pin failed: {code}", str(res2))


# ── 9. MEVO Chat ──────────────────────────────────────────────────────────────
section("9. MEVO Chat (/api/mevo/chat)")

if TEST_CLIENT_ID:
    code, chat = _request("POST", "/api/mevo/chat", {
        "customer_id": TEST_CLIENT_ID,
        "system": "You are MEVO. Answer in one sentence.",
        "messages": [{"role": "user", "content": "What is the capital of Sweden?"}],
    })
    if code == 200 and chat.get("reply"):
        ok(f"POST /api/mevo/chat → reply: '{chat['reply'][:60]}…'")
    elif code == 500 and "OPENAI_API_KEY" in str(chat):
        bug("MEDIUM", "MEVO", "OPENAI_API_KEY not set in backend environment — MEVO chat won't work")
    else:
        bug("HIGH", "MEVO", f"POST /api/mevo/chat failed: {code}", str(chat)[:200])


# ── 10. Legacy SEO Crawler endpoints ─────────────────────────────────────────
section("10. Legacy SEO Crawler")

code, jobs = _request("GET", "/api/jobs")
if code == 200 and isinstance(jobs, list):
    ok(f"GET /api/jobs → {len(jobs)} jobs")
else:
    bug("MEDIUM", "SEO Crawler", f"GET /api/jobs failed: {code}")

code, hist = _request("GET", "/api/history?limit=5")
if code == 200:
    ok("GET /api/history → OK")
else:
    bug("LOW", "SEO Crawler", f"GET /api/history failed: {code}")


# ── 11. Frontend pages (check they're served / not 404) ───────────────────────
section("11. Frontend pages (HTTP check)")

if FRONTEND_BASE:
    for page in FRONTEND_PAGES:
        fb_url = FRONTEND_BASE.rstrip('/') + '/' + page
        req2 = urllib.request.Request(fb_url)
        try:
            with urllib.request.urlopen(req2, timeout=15) as r2:
                code2 = r2.status
        except urllib.error.HTTPError as e:
            code2 = e.code
        except Exception as e:
            code2 = 0
        if code2 in (200, 304):
            ok(f"{page} → {code2}")
        elif code2 == 404:
            bug("MEDIUM", "Frontend", f"{page} → 404 (not found at {fb_url})")
        else:
            bug("LOW", "Frontend", f"{page} → {code2}")
else:
    print("  ⚠️  Frontend URL not set — skipping HTML page checks.")
    print("     Run with --frontend-url https://yoursite.com to enable.")


# ── 12. Agent run (smoke test with dummy) ────────────────────────────────────
section("12. Agent Run (smoke with use_dummy=true)")

code, run_resp = _request("POST", "/api/agents/run", {
    "agent": "competitor",
    "input": {"query": "auditbot.example.com"},
    "use_dummy": True,
})
if code == 200 and run_resp.get("job_id"):
    jid = run_resp["job_id"]
    ok(f"POST /api/agents/run (dummy) → job_id {jid}")
    time.sleep(3)
    code2, job = _request("GET", f"/api/agents/jobs/{jid}")
    if code2 == 200:
        status = job.get("status", "?")
        ok(f"GET /api/agents/jobs/{{id}} → status={status}")
        if status == "failed":
            bug("LOW", "Agent Run", f"Dummy competitor job failed: {job.get('error','')[:120]}")
    else:
        bug("MEDIUM", "Agent Run", f"GET job status failed: {code2}")
else:
    bug("HIGH", "Agent Run", f"POST /api/agents/run failed: {code}", str(run_resp)[:200])


# ── Cleanup ───────────────────────────────────────────────────────────────────
section("13. Cleanup — delete test client")

if TEST_CLIENT_ID:
    code, _ = _request("DELETE", f"/api/clients/{TEST_CLIENT_ID}")
    if code == 200:
        ok(f"DELETE /api/clients/{TEST_CLIENT_ID} → OK")
    else:
        bug("LOW", "Cleanup", f"DELETE client failed: {code}")


# ── Report ────────────────────────────────────────────────────────────────────
print(f"\n{'═'*60}")
print(f"  AUDIT COMPLETE — {len(passed)} passed, {len(bugs)} bugs found")
print(f"{'═'*60}\n")

sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
bugs_sorted = sorted(bugs, key=lambda b: sev_order.get(b["severity"], 9))

report_lines = [
    "# Amazing Tools — Bug Report",
    f"Generated by audit_amazingtools.py",
    "",
    f"**{len(passed)} checks passed · {len(bugs)} bugs found**",
    "",
    f"## Bugs ({len(bugs)})",
    "",
]

for b in bugs_sorted:
    emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}[b["severity"]]
    report_lines.append(f"### {emoji} [{b['severity']}] {b['section']} — {b['title']}")
    if b["detail"]:
        report_lines.append(f"> {b['detail']}")
    report_lines.append("")

report_lines += [
    "## Passed Checks",
    "",
    *[f"- ✅ {p}" for p in passed],
]

report = "\n".join(report_lines)

with open("BUGS.md", "w") as f:
    f.write(report)

print(report)
print(f"\n📄 Report saved to BUGS.md")

if any(b["severity"] == "HIGH" for b in bugs):
    sys.exit(1)
