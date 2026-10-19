
"""Smoke test executed inside every built image (CI)."""

import os
import sys

from shared import problems
from . import judge, sandbox

LANGUAGE = os.environ.get("LANGUAGE", "python")

HOSTILE = {
    "python": {
        "while True: pass\ndef fib(n):\n    return 0\n": "TIME_LIMIT_EXCEEDED",
        "import os\ndef fib(n):\n    os.system('id')\n": "RUNTIME_ERROR",
        "def fib(n):\n    x = bytearray(4 * 1024**3)\n": "MEMORY_LIMIT_EXCEEDED",
    },
    "javascript": {
        "function fib(n){ while(true){} }": "TIME_LIMIT_EXCEEDED",
        "function fib(n){ return process.env; }": "RUNTIME_ERROR",
        "function fib(n){ const a = new Array(50000000).fill(1); return a.length; }":
            "MEMORY_LIMIT_EXCEEDED",
    },
}


def main() -> int:
    if LANGUAGE not in HOSTILE:
        print(f"Unsupported LANGUAGE: {LANGUAGE!r}")
        return 2

    failures = []

    # Verify all reference solutions first.
    for problem in problems.PROBLEMS:
        result = judge.judge(
            LANGUAGE,
            problem["reference"][LANGUAGE],
            problem,
            problems.all_tests(problem),
        )
        if result["verdict"] != "ACCEPTED":
            failures.append(f"reference {problem['id']}: {result}")

    # Define the Fibonacci problem before running hostile-code tests.
    fib = problems.get_problem("fibonacci")

    for code, expected in HOSTILE[LANGUAGE].items():
        if LANGUAGE == "javascript" and expected == "MEMORY_LIMIT_EXCEEDED":
            result = sandbox.run_case(
                LANGUAGE,
                code,
                "fib",
                [1],
                time_limit_ms=10000,
                mem_mb=128,
            )
            actual = {
                "ok": "ACCEPTED",
                "error": "RUNTIME_ERROR",
                "timeout": "TIME_LIMIT_EXCEEDED",
                "mle": "MEMORY_LIMIT_EXCEEDED",
            }.get(result["status"], "RUNTIME_ERROR")
        else:
            result = judge.judge(
                LANGUAGE,
                code,
                fib,
                problems.all_tests(fib)[:1],
            )
            actual = result["verdict"]

        if actual != expected:
            failures.append(
                f"hostile {expected!r} -> {actual!r}: "
                f"{code[:40]!r}; result={result}"
            )

    if failures:
        print("selftest FAILED:\n" + "\n".join(failures))
    else:
        print(f"selftest OK ({LANGUAGE})")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
