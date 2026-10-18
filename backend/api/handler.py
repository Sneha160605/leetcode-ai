"""REST API (API Gateway proxy integration, Cognito-authorised)."""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from decimal import Decimal

from shared import ai, problems
from shared.store import Store, now_iso

log = logging.getLogger()
log.setLevel(logging.INFO)

MAX_CODE_CHARS = 20_000
HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": os.environ.get("ALLOWED_ORIGIN", "*"),
    "Access-Control-Allow-Headers": "Authorization,Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class Deps:
    """Lazily built AWS clients; tests replace `deps` with fakes."""

    def __init__(self):
        self._store = None
        self._sqs = None

    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = Store()
        return self._store

    def enqueue(self, language: str, body: dict) -> None:
        import boto3

        if self._sqs is None:
            self._sqs = boto3.client("sqs")
        kwargs = {}
        trace = os.environ.get("_X_AMZN_TRACE_ID")
        if trace:  # links the Lambda segment to the worker's processing in X-Ray
            kwargs["MessageSystemAttributes"] = {"AWSTraceHeader": {"DataType": "String", "StringValue": trace}}
        self._sqs.send_message(QueueUrl=os.environ[f"QUEUE_URL_{language.upper()}"], MessageBody=json.dumps(body), **kwargs)


deps = Deps()


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(type(o))


def resp(status: int, body) -> dict:
    return {"statusCode": status, "headers": HEADERS, "body": json.dumps(body, default=_default)}


def _identity(event) -> dict:
    claims = (event.get("requestContext", {}).get("authorizer") or {}).get("claims") or {}
    if not claims.get("sub"):
        raise ApiError(401, "Unauthenticated")
    name = (claims.get("email") or "").split("@")[0] or claims.get("cognito:username") or "anon"
    return {"sub": claims["sub"], "name": name, "admin": "admins" in str(claims.get("cognito:groups", ""))}


def _body(event) -> dict:
    try:
        data = json.loads(event.get("body") or "{}")
    except ValueError:
        raise ApiError(400, "Body must be JSON")
    if not isinstance(data, dict):
        raise ApiError(400, "Body must be a JSON object")
    return data


def _problem(pid) -> dict:
    p = problems.get_problem(str(pid))
    if not p:
        raise ApiError(404, "Unknown problem")
    return p


# ------------------------------------------------------------------ routes
def list_problems(user, event, **_):
    solved = set(deps.store.solved_ids(user["sub"]))
    return 200, [dict(problems.public_summary(p), solved=p["id"] in solved) for p in problems.PROBLEMS]


def get_problem(user, event, pid, **_):
    return 200, problems.public_detail(_problem(pid))


def submit(user, event, **_):
    b = _body(event)
    p = _problem(b.get("problemId"))
    language, code = b.get("language"), b.get("code")
    if language not in problems.LANGUAGES:
        raise ApiError(400, f"language must be one of {list(problems.LANGUAGES)}")
    if not isinstance(code, str) or not code.strip():
        raise ApiError(400, "code is required")
    if len(code) > MAX_CODE_CHARS:
        raise ApiError(413, f"code exceeds {MAX_CODE_CHARS} characters")
    sub = {"id": str(uuid.uuid4()), "user": user["sub"], "userName": user["name"], "problemId": p["id"],
           "language": language, "code": code, "status": "QUEUED", "createdAt": now_iso()}
    deps.store.create_submission(sub)
    try:
        deps.enqueue(language, {"type": "judge", "submissionId": sub["id"]})
    except Exception:
        log.exception("enqueue failed")
        deps.store.update_submission(sub["id"], status="FAILED", verdict="SYSTEM_ERROR")
        raise ApiError(503, "Judge queue unavailable, please retry")
    return 202, {"id": sub["id"], "status": "QUEUED"}


def get_submission(user, event, sid, **_):
    s = deps.store.get_submission(sid)
    if not s or s.get("user") != user["sub"]:
        raise ApiError(404, "Submission not found")
    return 200, {k: v for k, v in s.items() if k not in ("pk", "sk", "gsi1pk", "gsi1sk", "user")}


def list_submissions(user, event, **_):
    pid = (event.get("queryStringParameters") or {}).get("problemId")
    return 200, deps.store.list_user_submissions(user["sub"], pid)


def hint(user, event, **_):
    b = _body(event)
    p = _problem(b.get("problemId"))
    code = str(b.get("code") or "")[:ai.MAX_HINT_LEVEL * 2000]
    history = deps.store.list_hints(user["sub"], p["id"])
    if len(history) >= 12:
        raise ApiError(429, "Hint limit reached for this problem; try a few more attempts first")
    level = min(ai.MAX_HINT_LEVEL, len(history) + 1)
    verdict = None
    if b.get("submissionId"):
        s = deps.store.get_submission(str(b["submissionId"]))
        if s and s.get("user") == user["sub"]:
            verdict = s.get("result")
    out = ai.generate_hint(p, code, level, [h["text"] for h in history], verdict)
    deps.store.add_hint(user["sub"], p["id"], out["level"], out["hint"], out["source"])
    return 200, {"level": out["level"], "maxLevel": ai.MAX_HINT_LEVEL, "hint": out["hint"]}


def leaderboard(user, event, **_):
    return 200, deps.store.leaderboard()


def gen_tests(user, event, pid, **_):
    if not user["admin"]:
        raise ApiError(403, "Admins only")
    p = _problem(pid)
    deps.enqueue("python", {"type": "gentests", "problemId": p["id"]})
    return 202, {"status": "QUEUED"}


ROUTES = [
    ("GET", r"/problems", list_problems),
    ("GET", r"/problems/(?P<pid>[\w-]+)", get_problem),
    ("POST", r"/problems/(?P<pid>[\w-]+)/gentests", gen_tests),
    ("POST", r"/submissions", submit),
    ("GET", r"/submissions", list_submissions),
    ("GET", r"/submissions/(?P<sid>[\w-]+)", get_submission),
    ("POST", r"/hints", hint),
    ("GET", r"/leaderboard", leaderboard),
]


def handler(event, context=None):
    try:
        method, path = event.get("httpMethod", "GET"), (event.get("path") or "/").rstrip("/") or "/"
        if method == "OPTIONS":
            return {"statusCode": 204, "headers": HEADERS, "body": ""}
        for m, pattern, fn in ROUTES:
            match = re.fullmatch(pattern, path)
            if m == method and match:
                status, body = fn(_identity(event), event, **match.groupdict())
                return resp(status, body)
        return resp(404, {"error": "Not found"})
    except ApiError as e:
        return resp(e.status, {"error": e.message})
    except Exception:
        log.exception("unhandled")
        return resp(500, {"error": "Internal error"})
