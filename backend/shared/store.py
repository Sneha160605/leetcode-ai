"""DynamoDB single-table access layer.

Keys
  SUB#<id>/META            submission              gsi1: USER#<sub> / SUB#<iso-ts>     (user history)
  HINT#<sub>#<problem>/<ts> hint history
  USER#<sub>/PROG#<problem> first-solve marker (idempotent scoring)
  USER#<sub>/PROFILE        score + name         gsi1: LB / <score:09d>#<sub>        (leaderboard)
  TESTS#<problem>/META      LLM-generated, reference-verified extra tests
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Store:
    def __init__(self, table=None):
        if table is None:
            import boto3

            table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
        self.t = table

    # --- submissions
    def create_submission(self, sub: dict) -> None:
        item = dict(sub)
        item.update(pk=f"SUB#{sub['id']}", sk="META", gsi1pk=f"USER#{sub['user']}", gsi1sk=f"SUB#{sub['createdAt']}")
        self.t.put_item(Item=item)

    def get_submission(self, sub_id: str) -> dict | None:
        return self.t.get_item(Key={"pk": f"SUB#{sub_id}", "sk": "META"}).get("Item")

    def update_submission(self, sub_id: str, **fields) -> None:
        names = {f"#k{i}": k for i, k in enumerate(fields)}
        values = {f":v{i}": v for i, v in enumerate(fields.values())}
        expr = "SET " + ", ".join(f"#k{i} = :v{i}" for i in range(len(fields)))
        self.t.update_item(Key={"pk": f"SUB#{sub_id}", "sk": "META"}, UpdateExpression=expr,
                           ExpressionAttributeNames=names, ExpressionAttributeValues=values)

    def list_user_submissions(self, user: str, problem_id: str | None = None, limit: int = 20) -> list[dict]:
        resp = self.t.query(
            IndexName="gsi1", KeyConditionExpression=Key("gsi1pk").eq(f"USER#{user}") & Key("gsi1sk").begins_with("SUB#"),
            ScanIndexForward=False, Limit=100,
            ProjectionExpression="id, problemId, #l, #s, verdict, createdAt, passed, total",
            ExpressionAttributeNames={"#l": "language", "#s": "status"},
        )
        items = resp.get("Items", [])
        if problem_id:
            items = [i for i in items if i.get("problemId") == problem_id]
        return items[:limit]

    # --- hints
    def list_hints(self, user: str, problem_id: str) -> list[dict]:
        return self.t.query(KeyConditionExpression=Key("pk").eq(f"HINT#{user}#{problem_id}")).get("Items", [])

    def add_hint(self, user: str, problem_id: str, level: int, text: str, source: str) -> None:
        self.t.put_item(Item={"pk": f"HINT#{user}#{problem_id}", "sk": now_iso(), "level": level, "text": text, "source": source})

    # --- scoring
    def mark_solved(self, user: str, name: str, problem_id: str, pts: int) -> bool:
        """Award points once per (user, problem). Returns True if newly solved."""
        try:
            self.t.put_item(Item={"pk": f"USER#{user}", "sk": f"PROG#{problem_id}", "solvedAt": now_iso()},
                            ConditionExpression="attribute_not_exists(pk)")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        resp = self.t.update_item(
            Key={"pk": f"USER#{user}", "sk": "PROFILE"},
            UpdateExpression="ADD score :p, solved :one SET #n = :n, gsi1pk = :lb",
            ExpressionAttributeNames={"#n": "name"},
            ExpressionAttributeValues={":p": pts, ":one": 1, ":n": name, ":lb": "LB"}, ReturnValues="ALL_NEW")
        score = int(resp["Attributes"]["score"])
        self.t.update_item(Key={"pk": f"USER#{user}", "sk": "PROFILE"}, UpdateExpression="SET gsi1sk = :s",
                           ExpressionAttributeValues={":s": f"{score:09d}#{user}"})
        return True

    def solved_ids(self, user: str) -> list[str]:
        items = self.t.query(KeyConditionExpression=Key("pk").eq(f"USER#{user}") & Key("sk").begins_with("PROG#")).get("Items", [])
        return [i["sk"][5:] for i in items]

    def leaderboard(self, limit: int = 20) -> list[dict]:
        items = self.t.query(IndexName="gsi1", KeyConditionExpression=Key("gsi1pk").eq("LB"),
                             ScanIndexForward=False, Limit=limit).get("Items", [])
        return [{"rank": i + 1, "name": it.get("name", "anon"), "score": int(it["score"]), "solved": int(it.get("solved", 0))}
                for i, it in enumerate(items)]

    # --- generated tests
    def get_extra_tests(self, problem_id: str) -> list[dict]:
        item = self.t.get_item(Key={"pk": f"TESTS#{problem_id}", "sk": "META"}).get("Item")
        return item.get("tests", []) if item else []

    def put_extra_tests(self, problem_id: str, tests: list[dict]) -> None:
        self.t.put_item(Item={"pk": f"TESTS#{problem_id}", "sk": "META", "tests": tests, "updatedAt": now_iso()})
