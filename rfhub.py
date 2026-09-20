#!/usr/bin/env python3
"""Hub GitHub Actions helpers: suite/test check|run, acceptance-check|acceptance-run."""

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
PROJECT = os.environ.get("RFHUB_PROJECT", "").strip()
ACCEPTANCE = os.environ.get("RFHUB_ACCEPTANCE", "pr").strip() or "pr"
ENVIRONMENT = os.environ.get("RFHUB_ENVIRONMENT", "dev").strip() or "dev"
POLL = int(os.environ.get("RFHUB_POLL_SECONDS", "15") or "15")
WAIT = int(os.environ.get("RFHUB_WAIT_SECONDS", "900") or "900")
ACCEPTANCE_WAIT = int(os.environ.get("RFHUB_ACCEPTANCE_WAIT_SECONDS", "3600") or "3600")


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
        "User-Agent": "rfhub-actions/1.0",
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


def list_acceptance_reports():
    query = urllib.parse.urlencode({"project": PROJECT, "gitSha": SHA})
    status, payload, raw = req("GET", f"/api/agent/acceptance-reports?{query}")
    if status != 200 or not isinstance(payload, dict):
        die(f"GET /api/agent/acceptance-reports failed HTTP {status}: {raw[:400]}")
    reports = payload.get("reports")
    return reports if isinstance(reports, list) else []


def green_acceptance_report():
    """A ready+passed report for this definitionSlug+gitSha (not any green run)."""
    want = ACCEPTANCE.lower()
    for report in list_acceptance_reports():
        if not isinstance(report, dict):
            continue
        slug = str(report.get("definitionSlug") or "").strip().lower()
        if slug != want:
            continue
        if str(report.get("status") or "").lower() != "ready":
            continue
        if str(report.get("verdict") or "").lower() != "passed":
            continue
        return report
    return None


def queue_acceptance():
    if not BRANCH:
        die("GIT_BRANCH is empty")
    body = {
        "project": PROJECT,
        "branch": BRANCH,
        "environment": ENVIRONMENT,
        "gitSha": SHA,
        "acceptance": ACCEPTANCE,
    }
    status, payload, raw = req("POST", "/api/agent/acceptance-runs", body)
    if status not in {200, 201} or not isinstance(payload, dict):
        die(f"acceptance-runs failed HTTP {status}: {raw[:500]}")
    group_id = str(payload.get("groupId") or "")
    if not group_id:
        die(f"acceptance-runs response missing groupId: {raw[:400]}")
    print(f"queued acceptance {ACCEPTANCE} group={group_id} {HUB}/acceptance-runs/{group_id}")
    return group_id


def wait_acceptance(group_id):
    deadline = time.monotonic() + ACCEPTANCE_WAIT
    while time.monotonic() < deadline:
        status, payload, raw = req(
            "GET", f"/api/agent/acceptance-runs?{urllib.parse.urlencode({'groupId': group_id})}"
        )
        if status != 200 or not isinstance(payload, dict):
            print(f"poll HTTP {status}: {raw[:200]}", file=sys.stderr)
            time.sleep(POLL)
            continue
        group_status = str(payload.get("status") or "").lower()
        report = payload.get("report") if isinstance(payload.get("report"), dict) else None
        verdict = str((report or {}).get("verdict") or "").lower() if report else ""
        report_status = str((report or {}).get("status") or "").lower() if report else ""
        print(
            f"  group={group_status} report={report_status or '-'} verdict={verdict or '-'}"
        )
        if group_status in {"running", "queued", ""}:
            time.sleep(POLL)
            continue
        if group_status == "cancelled":
            die(f"acceptance cancelled {group_id}")
        if group_status == "merged":
            if report_status == "ready" and verdict == "passed":
                return report
            die(
                f"acceptance merged but not green group={group_id} "
                f"report={report_status} verdict={verdict} {HUB}/acceptance-runs/{group_id}"
            )
        # completed/failed without merge yet — keep waiting briefly for report auto-create
        if group_status in {"completed", "failed"} and not report:
            time.sleep(POLL)
            continue
        if group_status == "failed":
            die(f"acceptance failed {group_id} {HUB}/acceptance-runs/{group_id}")
        time.sleep(POLL)
    die(f"timed out waiting for acceptance {group_id}")


def cmd_check():
    if not RID or not SHA:
        die("RFHUB_ID and GIT_SHA are required")
    ok = already_passed()
    out(passed="true" if ok else "false")
    if not ok:
        die(f"{RID} has no passing run for {SHA[:12]}")
    print(f"{RID} passed on {SHA[:12]}")


def cmd_run():
    if not RID or not SHA:
        die("RFHUB_ID and GIT_SHA are required")
    handle = queue()
    out(handle=handle, passed="false")
    wait(handle)
    out(passed="true")
    print(f"{RID} passed {handle}")


def cmd_acceptance_check():
    if not PROJECT or not SHA:
        die("RFHUB_PROJECT and GIT_SHA are required")
    report = green_acceptance_report()
    if not report:
        out(passed="false")
        die(f"acceptance '{ACCEPTANCE}' has no green report for {SHA[:12]}")
    report_id = str(report.get("id") or "")
    out(passed="true", reportId=report_id)
    print(f"acceptance '{ACCEPTANCE}' green report {report_id} on {SHA[:12]}")


def cmd_acceptance_run():
    if not PROJECT or not SHA:
        die("RFHUB_PROJECT and GIT_SHA are required")
    existing = green_acceptance_report()
    if existing:
        report_id = str(existing.get("id") or "")
        out(passed="true", reportId=report_id, groupId="")
        print(f"acceptance '{ACCEPTANCE}' already green {report_id} on {SHA[:12]}")
        return
    group_id = queue_acceptance()
    out(groupId=group_id, passed="false")
    report = wait_acceptance(group_id)
    report_id = str((report or {}).get("id") or "")
    out(passed="true", reportId=report_id)
    print(f"acceptance '{ACCEPTANCE}' passed report={report_id} group={group_id}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in {"check", "run", "acceptance-check", "acceptance-run"}:
        die("usage: rfhub.py check|run|acceptance-check|acceptance-run", 2)
    if not TOKEN:
        die("RFHUB_TOKEN is empty")
    if cmd == "check":
        cmd_check()
    elif cmd == "run":
        cmd_run()
    elif cmd == "acceptance-check":
        cmd_acceptance_check()
    else:
        cmd_acceptance_run()


if __name__ == "__main__":
    main()
