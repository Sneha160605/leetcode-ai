"""Offline throughput check of the judge core (no AWS): N submissions across W parallel workers.

python3 loadtest/queue_sim.py [submissions=60] [workers=4]   (run from repo root)
Use it to size `maxTasks`: tasks needed ~= arrival_rate * avg_judge_seconds.
"""
import os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from shared import problems  # noqa: E402
from judge import judge  # noqa: E402

n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
w = int(sys.argv[2]) if len(sys.argv) > 2 else 4
p = problems.get_problem("two-sum")
tests = problems.all_tests(p)

def one(_):
    t = time.monotonic()
    return judge.judge("python", p["reference"]["python"], p, tests)["verdict"], time.monotonic() - t

t0 = time.monotonic()
with ThreadPoolExecutor(w) as ex:
    res = list(ex.map(one, range(n)))
wall = time.monotonic() - t0
lat = sorted(r[1] for r in res)
print(f"{n} submissions, {w} workers: {n / wall:.1f}/s, avg {sum(lat) / n:.2f}s, p95 {lat[int(n * .95) - 1]:.2f}s, "
      f"accepted {sum(r[0] == 'ACCEPTED' for r in res)}/{n}")
