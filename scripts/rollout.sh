#!/usr/bin/env bash
# Staged rollout of a new judge image: 10% canary -> soak -> alarm gate -> 100%. Rolls back on failure.
# usage: scripts/rollout.sh <new-tag> [previous-tag] [soak-seconds]
set -euo pipefail
NEW="$1"; PREV="${2:-}"; SOAK="${3:-300}"
cd "$(dirname "$0")/../infra"
deploy() { npx cdk deploy LeetAI-Platform --require-approval never "$@"; }

if [[ -z "$PREV" ]]; then
  echo ">> first deployment: straight to 100% ($NEW)"; deploy -c stableTag="$NEW"; exit 0
fi

echo ">> stage 1: canary 10% on $NEW, 90% stays on $PREV"
deploy -c stableTag="$PREV" -c canaryTag="$NEW" -c canaryPercent=10

echo ">> soaking ${SOAK}s, watching leetai-judge-health"
end=$((SECONDS + SOAK))
while (( SECONDS < end )); do
  state=$(aws cloudwatch describe-alarms --alarm-names leetai-judge-health --query 'CompositeAlarms[0].StateValue' --output text)
  if [[ "$state" == "ALARM" ]]; then
    echo "!! health alarm fired, rolling back to $PREV"; deploy -c stableTag="$PREV"; exit 1
  fi
  sleep 15
done

echo ">> stage 2: promote $NEW to 100%"
deploy -c stableTag="$NEW"
