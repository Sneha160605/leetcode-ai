"""SQS consumer that runs on Fargate (one image per language runtime).

Flow: receive -> mark RUNNING -> judge in sandbox -> persist verdict -> score -> AI review -> delete message.
Failures leave the message for redelivery; after maxReceiveCount the SQS redrive policy moves it to the DLQ.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import time

from shared import ai, problems
from shared.store import Store, now_iso

from . import judge as judge_mod
from . import sandbox

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("worker")

LANGUAGE = os.environ.get("LANGUAGE", "python")
_stop = False


def emit_metrics(language: str, **metrics) -> None:
    """CloudWatch Embedded Metric Format: one structured log line becomes metrics + stays searchable."""
    units = {"JudgeDurationMs": "Milliseconds", "QueueWaitMs": "Milliseconds", "SlowestTestMs": "Milliseconds"}
    print(json.dumps({
        "_aws": {"Timestamp": int(time.time() * 1000), "CloudWatchMetrics": [{
            "Namespace": "LeetAI/Judge", "Dimensions": [["Language"]],
            "Metrics": [{"Name": k, "Unit": units.get(k, "Count")} for k in metrics]}]},
        "Language": language, **metrics}), flush=True)


def process_judge(store: Store, sub_id: str, trace: str | None = None) -> None:
    sub = store.get_submission(sub_id)
    if not sub:
        log.warning(json.dumps({"event": "missing_submission", "id": sub_id}))
        return
    if sub.get("status") == "DONE":  # SQS is at-least-once: make redelivery harmless
        return
    problem = problems.get_problem(sub["problemId"])
    store.update_submission(sub_id, status="RUNNING", startedAt=now_iso())
    started = time.monotonic()
    tests = problems.all_tests(problem, store.get_extra_tests(problem["id"]))
    result = judge_mod.judge(sub["language"], sub["code"], problem, tests)
    duration_ms = int((time.monotonic() - started) * 1000)
    store.update_submission(sub_id, status="DONE", verdict=result["verdict"], passed=result["passed"],
                            total=result["total"], result=result, finishedAt=now_iso())
    log.info(json.dumps({"event": "judged", "id": sub_id, "problem": problem["id"], "language": sub["language"],
                         "verdict": result["verdict"], "duration_ms": duration_ms, "trace": trace}))
    emit_metrics(sub["language"], JudgeDurationMs=duration_ms, SlowestTestMs=result.get("max_ms", 0),
                 Submissions=1, TimeLimitExceeded=int(result["verdict"] == "TIME_LIMIT_EXCEEDED"),
                 RuntimeErrors=int(result["verdict"] == "RUNTIME_ERROR"))
    if result["verdict"] == "ACCEPTED":
        store.mark_solved(sub["user"], sub.get("userName", "anon"), problem["id"], problems.points(problem))
    # AI review only for code that ran to completion in a meaningful way; never blocks the verdict.
    if result["verdict"] in ("ACCEPTED", "WRONG_ANSWER", "TIME_LIMIT_EXCEEDED"):
        try:
            store.update_submission(sub_id, review=ai.review_code(problem, sub["language"], sub["code"], result))
        except Exception as e:  # noqa: BLE001
            log.warning(json.dumps({"event": "review_failed", "id": sub_id, "error": str(e)[:200]}))
            store.update_submission(sub_id, reviewError=True)


def process_gentests(store: Store, problem_id: str) -> None:
    """LLM proposes edge-case inputs; the trusted reference solution (run in the sandbox) provides expected outputs."""
    problem = problems.get_problem(problem_id)
    verified = []
    for args in ai.suggest_test_inputs(problem):
        run = sandbox.run_case("python", problem["reference"]["python"], problem["function"]["python"], args, 5000)
        if run["status"] == "ok":
            verified.append({"args": args, "expected": run["output"]})
    store.put_extra_tests(problem_id, verified)
    log.info(json.dumps({"event": "gentests", "problem": problem_id, "accepted": len(verified)}))


def process_message(store: Store, body: dict, trace: str | None = None) -> None:
    kind = body.get("type")
    if kind == "judge":
        process_judge(store, body["submissionId"], trace)
    elif kind == "gentests":
        process_gentests(store, body["problemId"])
    else:
        raise ValueError(f"unknown job type {kind!r}")


def _handle_signal(*_):
    global _stop
    _stop = True


def run() -> None:
    import boto3

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    sqs = boto3.client("sqs")
    queue_url = os.environ["QUEUE_URL"]
    store = Store()
    log.info(json.dumps({"event": "worker_started", "language": LANGUAGE, "version": os.environ.get("IMAGE_TAG", "dev")}))
    while not _stop:
        resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=20,
                                   AttributeNames=["SentTimestamp", "ApproximateReceiveCount", "AWSTraceHeader"])
        for msg in resp.get("Messages", []):
            attrs = msg.get("Attributes", {})
            try:
                if "SentTimestamp" in attrs:
                    emit_metrics(LANGUAGE, QueueWaitMs=max(0, int(time.time() * 1000) - int(attrs["SentTimestamp"])))
                process_message(store, json.loads(msg["Body"]), attrs.get("AWSTraceHeader"))
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
            except Exception:  # noqa: BLE001
                log.exception("job failed (attempt %s)", attrs.get("ApproximateReceiveCount"))


if __name__ == "__main__":
    run()
