"""Turns sandbox runs into a verdict."""
from __future__ import annotations

from . import sandbox

TIME_LIMIT_MS = {"python": 2000, "javascript": 2000}


def outputs_match(actual, expected, mode: str = "exact") -> bool:
    if mode == "sorted" and isinstance(actual, list) and isinstance(expected, list):
        try:
            return sorted(actual) == sorted(expected)
        except TypeError:
            return False
    return _norm(actual) == _norm(expected)


def _norm(v):
    # JSON round-trips ints/floats identically (1 == 1.0); bools must stay bools
    if isinstance(v, bool):
        return ("bool", v)  # keep distinct from 1/0, since True == 1 in Python
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return float(v) if isinstance(v, float) and not float(v).is_integer() else int(v)
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    return v


def judge(language: str, code: str, problem: dict, tests: list[dict]) -> dict:
    fn = problem["function"][language]
    limit = problem.get("time_limit_ms", TIME_LIMIT_MS[language])
    passed, max_ms, total_ms = 0, 0.0, 0.0
    result = {"verdict": "ACCEPTED", "passed": 0, "total": len(tests)}
    for i, t in enumerate(tests):
        run = sandbox.run_case(language, code, fn, t["args"], time_limit_ms=limit)
        max_ms = max(max_ms, float(run.get("ms") or 0))
        total_ms += float(run.get("ms") or 0)
        if run["status"] == "ok" and outputs_match(run.get("output"), t["expected"], problem.get("compare", "exact")):
            passed += 1
            continue
        verdict = {"ok": "WRONG_ANSWER", "error": "RUNTIME_ERROR", "timeout": "TIME_LIMIT_EXCEEDED",
                   "mle": "MEMORY_LIMIT_EXCEEDED"}[run["status"]]
        fail = {"index": i + 1, "hidden": bool(t.get("hidden"))}
        if not t.get("hidden"):  # never reveal hidden inputs/expected values
            fail.update(input=t["args"], expected=t["expected"])
            if run["status"] == "ok":
                fail["actual"] = run.get("output")
        if run.get("error"):
            fail["error"] = run["error"]
        if run.get("stdout"):
            fail["stdout"] = run["stdout"][-500:]
        result.update(verdict=verdict, failure=fail)
        break
    result.update(passed=passed, max_ms=round(max_ms, 1), total_ms=round(total_ms, 1))
    return result
