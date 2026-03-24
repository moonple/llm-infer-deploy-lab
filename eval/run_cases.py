"""Evaluation harness for the llama.cpp inference server.

Modes
-----
offline (default / CI)
    Validates test-case schema only – no running server required.
online
    Sends each case to the server and checks quality gates.

Error types
-----------
runtime_error  – HTTP / network error reaching the server
timeout_error  – request exceeded the case's timeout_s
quality_error  – server responded but the response failed a quality check
config_error   – test-case definition is missing required fields

Usage
-----
    python3 eval/run_cases.py --offline
    python3 eval/run_cases.py --server http://localhost:8080
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

CASES_FILE = Path(__file__).parent / "cases.json"
REPORT_JSON = Path(__file__).parent / "report.json"
REPORT_MD = Path(__file__).parent / "report.md"

# Stable error-type enum values
ERROR_RUNTIME = "runtime_error"
ERROR_TIMEOUT = "timeout_error"
ERROR_QUALITY = "quality_error"
ERROR_CONFIG = "config_error"

REQUIRED_CASE_FIELDS = {"id", "prompt"}


@dataclass
class CaseResult:
    id: str
    ok: bool
    error_type: Optional[str]
    error_message: Optional[str]
    duration_ms: float
    timings_ms: dict = field(default_factory=dict)
    response_preview: Optional[str] = None


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------

def _check_quality(response: dict, case: dict) -> tuple[bool, Optional[str]]:
    """Return (passed, failure_message)."""
    text = response.get("content") or response.get("response") or ""

    if "expect_min_len" in case:
        min_len = int(case["expect_min_len"])
        if len(text) < min_len:
            return False, f"response too short: {len(text)} chars < {min_len}"

    for term in case.get("expect_contains", []):
        if term.lower() not in text.lower():
            return False, f"response missing expected term: {term!r}"

    return True, None


# ---------------------------------------------------------------------------
# Case runners
# ---------------------------------------------------------------------------

def run_case_online(case: dict, server_url: str) -> CaseResult:
    """Run one case against a live server."""
    t0 = time.perf_counter()
    payload = {
        "prompt": case["prompt"],
        "n_predict": case.get("n_predict", 128),
        "temperature": case.get("temperature", 0.0),
    }
    req = urllib.request.Request(
        f"{server_url.rstrip('/')}/completion",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=case.get("timeout_s", 30)) as resp:
            raw = resp.read()
        dur_ms = (time.perf_counter() - t0) * 1000.0

        try:
            body = json.loads(raw)
        except json.JSONDecodeError as json_exc:
            return CaseResult(
                id=case["id"],
                ok=False,
                error_type=ERROR_RUNTIME,
                error_message=f"invalid JSON response: {json_exc}",
                duration_ms=dur_ms,
                timings_ms={"total_ms": dur_ms},
            )

        quality_ok, quality_msg = _check_quality(body, case)
        if not quality_ok:
            return CaseResult(
                id=case["id"],
                ok=False,
                error_type=ERROR_QUALITY,
                error_message=quality_msg,
                duration_ms=dur_ms,
                timings_ms={"total_ms": dur_ms},
                response_preview=(body.get("content") or body.get("response") or "")[:200],
            )

        return CaseResult(
            id=case["id"],
            ok=True,
            error_type=None,
            error_message=None,
            duration_ms=dur_ms,
            timings_ms={"total_ms": dur_ms},
            response_preview=(body.get("content") or body.get("response") or "")[:200],
        )

    except urllib.error.URLError as exc:
        dur_ms = (time.perf_counter() - t0) * 1000.0
        # urllib wraps socket.timeout (a TimeoutError subclass) inside URLError;
        # check the reason to emit the stable timeout_error type.
        if isinstance(exc.reason, TimeoutError):
            return CaseResult(
                id=case["id"],
                ok=False,
                error_type=ERROR_TIMEOUT,
                error_message=f"request timed out after {case.get('timeout_s', 30)}s",
                duration_ms=dur_ms,
                timings_ms={"total_ms": dur_ms},
            )
        return CaseResult(
            id=case["id"],
            ok=False,
            error_type=ERROR_RUNTIME,
            error_message=str(exc),
            duration_ms=dur_ms,
            timings_ms={"total_ms": dur_ms},
        )


def run_case_offline(case: dict) -> CaseResult:
    """Validate case schema only – no server required."""
    missing = REQUIRED_CASE_FIELDS - set(case.keys())
    if missing:
        return CaseResult(
            id=case.get("id", "<unknown>"),
            ok=False,
            error_type=ERROR_CONFIG,
            error_message=f"missing required fields: {sorted(missing)}",
            duration_ms=0.0,
            timings_ms={"total_ms": 0.0},
        )
    return CaseResult(
        id=case["id"],
        ok=True,
        error_type=None,
        error_message=None,
        duration_ms=0.0,
        timings_ms={"total_ms": 0.0},
    )


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------

def _build_report(results: list[CaseResult], mode: str) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r.ok)
    failed = total - passed

    fail_type_counts: dict[str, int] = {}
    for r in results:
        if r.error_type:
            fail_type_counts[r.error_type] = fail_type_counts.get(r.error_type, 0) + 1

    return {
        "mode": mode,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "runtime_fail_count": fail_type_counts.get(ERROR_RUNTIME, 0)
            + fail_type_counts.get(ERROR_TIMEOUT, 0),
            "quality_fail_count": fail_type_counts.get(ERROR_QUALITY, 0),
            "config_fail_count": fail_type_counts.get(ERROR_CONFIG, 0),
            "fail_type_counts": fail_type_counts,
        },
        "cases": [
            {
                "id": r.id,
                "ok": r.ok,
                "error_type": r.error_type,
                "error_message": r.error_message,
                "duration_ms": r.duration_ms,
                "timings_ms": r.timings_ms,
                "response_preview": r.response_preview,
            }
            for r in results
        ],
    }


def _build_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# Eval Report",
        "",
        f"**Mode**: `{report['mode']}`",
        "",
        "## Summary",
        "",
        "| Total | Passed | Failed | Runtime Fails | Quality-Gate Fails |",
        "|-------|--------|--------|---------------|--------------------|",
        f"| {s['total']} | {s['passed']} | {s['failed']} "
        f"| {s['runtime_fail_count']} | {s['quality_fail_count']} |",
        "",
    ]

    if s.get("fail_type_counts"):
        lines += ["## Failure Breakdown by Error Type", ""]
        for err_type, count in sorted(s["fail_type_counts"].items()):
            lines.append(f"- `{err_type}`: {count}")
        lines.append("")

    lines += [
        "## Case Results",
        "",
        "| ID | Status | Error Type | Duration (ms) | Message |",
        "|----|--------|------------|---------------|---------|",
    ]
    for c in report["cases"]:
        status = "✅" if c["ok"] else "❌"
        dur = f"{c['duration_ms']:.1f}"
        err_type = f"`{c['error_type']}`" if c["error_type"] else "-"
        msg = (c["error_message"] or "-")[:80].replace("|", "\\|")
        lines.append(f"| {c['id']} | {status} | {err_type} | {dur} | {msg} |")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run LLM inference eval cases against the llama.cpp server."
    )
    parser.add_argument(
        "--server",
        default=None,
        metavar="URL",
        help="Server base URL, e.g. http://localhost:8080  (enables online mode)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Schema-validation only; no server required (default when --server is omitted)",
    )
    args = parser.parse_args()

    mode = "online" if (args.server and not args.offline) else "offline"

    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    results: list[CaseResult] = []

    print(f"Running {len(cases)} case(s) in {mode!r} mode …")
    for case in cases:
        if mode == "online":
            result = run_case_online(case, args.server)
        else:
            result = run_case_offline(case)
        results.append(result)
        tag = "PASS" if result.ok else f"FAIL({result.error_type})"
        print(f"  [{tag:30s}] {result.id}")

    report = _build_report(results, mode)
    REPORT_JSON.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    REPORT_MD.write_text(_build_markdown(report), encoding="utf-8")

    s = report["summary"]
    print(f"\nResults: {s['passed']}/{s['total']} passed")
    if s["runtime_fail_count"]:
        print(f"  Runtime failures  : {s['runtime_fail_count']}")
    if s["quality_fail_count"]:
        print(f"  Quality-gate fails: {s['quality_fail_count']}")
    if s["config_fail_count"]:
        print(f"  Config errors     : {s['config_fail_count']}")

    print(f"\nReports written to:\n  {REPORT_JSON}\n  {REPORT_MD}")
    sys.exit(0 if s["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
