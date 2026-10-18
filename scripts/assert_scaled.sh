#!/usr/bin/env bash
# After a load test: prove autoscaling reacted (peak running tasks > baseline). usage: assert_scaled.sh <cluster> <baseline>
set -euo pipefail
CLUSTER="$1"; BASE="${2:-2}"
peak=0
for svc in $(aws ecs list-services --cluster "$CLUSTER" --query 'serviceArns[]' --output text); do
  n=$(aws ecs describe-services --cluster "$CLUSTER" --services "$svc" --query 'services[0].runningCount' --output text)
  peak=$((peak + n))
done
echo "running tasks now: $peak (baseline $BASE)"
(( peak > BASE )) || { echo "autoscaling did not scale out"; exit 1; }
