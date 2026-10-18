"""Lets the suite run without boto3 installed, and provides an in-memory Store."""
import sys
import types


def install():
    if "boto3" in sys.modules:
        return
    boto3 = types.ModuleType("boto3")
    cond = types.ModuleType("boto3.dynamodb.conditions")
    ddb = types.ModuleType("boto3.dynamodb")
    cond.Key = lambda *a, **k: None
    bc = types.ModuleType("botocore")
    bce = types.ModuleType("botocore.exceptions")

    class ClientError(Exception):
        def __init__(self, response, op):
            super().__init__(op)
            self.response = response

    bce.ClientError = ClientError
    for name, mod in {"boto3": boto3, "boto3.dynamodb": ddb, "boto3.dynamodb.conditions": cond,
                      "botocore": bc, "botocore.exceptions": bce}.items():
        sys.modules[name] = mod


install()

from shared.store import now_iso  # noqa: E402


class FakeStore:
    def __init__(self):
        self.subs, self.hints, self.solved, self.scores, self.extra = {}, {}, {}, {}, {}

    def create_submission(self, sub):
        self.subs[sub["id"]] = dict(sub)

    def get_submission(self, sid):
        return self.subs.get(sid)

    def update_submission(self, sid, **f):
        self.subs[sid].update(f)

    def list_user_submissions(self, user, problem_id=None, limit=20):
        return [s for s in self.subs.values() if s["user"] == user and (not problem_id or s["problemId"] == problem_id)][:limit]

    def list_hints(self, user, pid):
        return self.hints.get((user, pid), [])

    def add_hint(self, user, pid, level, text, source):
        self.hints.setdefault((user, pid), []).append({"level": level, "text": text, "source": source})

    def mark_solved(self, user, name, pid, pts):
        if (user, pid) in self.solved:
            return False
        self.solved[(user, pid)] = now_iso()
        self.scores[user] = self.scores.get(user, 0) + pts
        return True

    def solved_ids(self, user):
        return [p for (u, p) in self.solved if u == user]

    def leaderboard(self, limit=20):
        return [{"rank": i + 1, "name": u, "score": s, "solved": 1} for i, (u, s) in
                enumerate(sorted(self.scores.items(), key=lambda kv: -kv[1]))]

    def get_extra_tests(self, pid):
        return self.extra.get(pid, [])

    def put_extra_tests(self, pid, tests):
        self.extra[pid] = tests
