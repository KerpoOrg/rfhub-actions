#!/usr/bin/env python3
"""Check or queue a Hub suite/test UUID for the current git SHA."""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HUB = "https://rfhub.kerpo.org"
TOKEN = os.environ.get("RFHUB_TOKEN", "").strip()
RID = os.environ.get("RFHUB_ID", "").strip()
SHA = os.environ.get("GIT_SHA", "").strip()
BRANCH = os.environ.get("GIT_BRANCH", "").strip()
POLL = 15
WAIT = 900


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def out(**kwargs):
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        for k, v in kwargs.items():
            print(f"{k}={v}")
        return
    with open(path, "a", encoding="utf-8") as fh:
        for k, v in kwargs.items():
            fh.write(f"{k}={v}\n")


def req(method, path, body=None):
    data = None
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{HUB}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None, raw
    except urllib.error.HTTPError as err:
        raw = err.read().decode(errors="replace")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = None
        return err.code, parsed, raw


def list_runs(**params):
    params.setdefault("limit", "50")
    query = urllib.parse.urlencode(params)
    status, payload, raw = req("GET", f"/api/agent/runs?{query}")
    if status != 200 or not isinstance(payload, dict):
        die(f"GET /api/agent/runs failed HTTP {status}: {raw[:400]}")
    runs = payload.get("runs")
    return runs if isinstance(runs, list) else []


def test_passed():
    for run in list_runs(gitSha=SHA):
        run_id = run.get("runId")
        if not run_id:
            continue
        status, payload, _ = req("GET", f"/api/agent/runs/{run_id}/tests/{RID}")
        if status == 200 and isinstance(payload, dict):
            if str(payload.get("status") or "").lower() == "passed":
                return True
    return False


def suite_passed():
    for run in list_runs(gitSha=SHA, suite=RID):
        if str(run.get("status") or "").lower() == "passed":
            return True
    return False


def already_passed():
    return test_passed() or suite_passed()


def resolve_project():
    for params in ({"test": RID}, {"suite": RID}, {"gitSha": SHA}):
        runs = list_runs(limit="1", **params)
        if runs:
            project = runs[0].get("projectId")
            if project:
                return project
    die("could not resolve Hub project for this id")


def queue():
    project = resolve_project()
    if not BRANCH:
        die("GIT_BRANCH is empty")
    base = {"project": project, "branch": BRANCH, "gitSha": SHA}
    status, payload, raw = req("POST", "/api/agent/queue", {**base, "testIds": [RID]})
    if status == 400:
        status, payload, raw = req("POST", "/api/agent/queue", {**base, "suiteIds": [RID]})
    if status not in {200, 201} or not isinstance(payload, dict):
        die(f"queue failed HTTP {status}: {raw[:500]}")
    handle = str(payload.get("handle") or payload.get("runId") or "")
    if not handle:
        die(f"queue response missing handle: {raw[:400]}")
    print(f"queued {handle} {HUB}/runs/{handle}")
    return handle


def wait(handle):
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        status, payload, raw = req("GET", f"/api/agent/batches/{handle}")
        if status != 200 or not isinstance(payload, dict):
            print(f"poll HTTP {status}: {raw[:200]}", file=sys.stderr)
            time.sleep(POLL)
            continue
        job = str(payload.get("jobStatus") or "").lower()
        run_status = str(payload.get("runStatus") or "").lower()
        in_progress = bool(payload.get("inProgress"))
        progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
        print(f"  {job} inProgress={in_progress} run={run_status} failed={progress.get('failed', 0)}")
        if in_progress or job in {"queued", "notified", "running", "accepted", ""}:
            time.sleep(POLL)
            continue
        if job == "cancelled":
            die(f"cancelled {handle}")
        failed = int(progress.get("failed") or 0)
        if job == "failed" or run_status == "failed" or failed:
            die(f"failed {handle} job={job} run={run_status} {HUB}/runs/{handle}")
        if not already_passed():
            die(f"finished but id did not pass {handle}")
        return
    die(f"timed out waiting for {handle}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in {"check", "run"}:
        die("usage: rfhub.py check|run", 2)
    if not TOKEN:
        die("RFHUB_TOKEN is empty")
    if not RID or not SHA:
        die("RFHUB_ID and GIT_SHA are required")
    if cmd == "check":
        ok = already_passed()
        out(passed="true" if ok else "false")
        if not ok:
            die(f"{RID} has no passing run for {SHA[:12]}")
        print(f"{RID} passed on {SHA[:12]}")
        return
    handle = queue()
    out(handle=handle, passed="false")
    wait(handle)
    out(passed="true")
    print(f"{RID} passed {handle}")


if __name__ == "__main__":
    main()
