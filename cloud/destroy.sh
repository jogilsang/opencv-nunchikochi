#!/usr/bin/env bash
# Tear down the nunchikochi stack in ONE command. OWNER: cloud tab.
#
# Empties the S3 buckets (CloudFormation cannot delete non-empty buckets), deletes the
# stack (all other resources go with it), then removes the out-of-stack code bucket.
# The SSM api-key parameter is left in place by default (it is a secret you created);
# pass --purge-key to also delete it.
#
# C2 is author + static validation only: --dry-run (DEFAULT) prints every mutating
# command without executing. Pass --apply to actually destroy (that is C3).
#
# Usage: cloud/destroy.sh [--apply] [--profile captain] [--region us-east-1] [--stack nunchi] [--purge-key]
set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE=captain REGION=us-east-1 STACK=nunchi APPLY=0 PURGE_KEY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --dry-run) APPLY=0 ;;
    --profile) PROFILE="$2"; shift ;;
    --region) REGION="$2"; shift ;;
    --stack) STACK="$2"; shift ;;
    --purge-key) PURGE_KEY=1 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

AWS=(aws --profile "$PROFILE" --region "$REGION")
ACCOUNT=$("${AWS[@]}" sts get-caller-identity --query Account --output text 2>/dev/null || echo ACCOUNT)
ACCOUNT_MASK="***${ACCOUNT: -4}"
WEB_BUCKET="${STACK}-web-${ACCOUNT}"
CODE_BUCKET="${STACK}-code-${ACCOUNT}"
API_KEY_PARAM="/nunchi/api-key"

run() { local shown="$*"; shown="${shown//$ACCOUNT/$ACCOUNT_MASK}"; echo "  \$ $shown"; if [ "$APPLY" = "1" ]; then "$@"; fi; }

echo "== nunchikochi destroy (apply=$APPLY, profile=$PROFILE, region=$REGION, stack=$STACK) =="

echo "[1/4] empty web bucket (${STACK}-web-${ACCOUNT_MASK}) so the stack can delete it"
run "${AWS[@]}" s3 rm "s3://$WEB_BUCKET" --recursive

echo "[2/4] delete stack (Lambda, Function URL, DynamoDB, CloudFront, logs, role, budget)"
run "${AWS[@]}" cloudformation delete-stack --stack-name "$STACK"
echo "  \$ ${AWS[*]} cloudformation wait stack-delete-complete --stack-name $STACK"
if [ "$APPLY" = "1" ]; then "${AWS[@]}" cloudformation wait stack-delete-complete --stack-name "$STACK"; fi

echo "[3/4] remove out-of-stack code bucket (${STACK}-code-${ACCOUNT_MASK})"
run "${AWS[@]}" s3 rm "s3://$CODE_BUCKET" --recursive
run "${AWS[@]}" s3api delete-bucket --bucket "$CODE_BUCKET"

echo "[4/4] api-key SSM parameter"
if [ "$PURGE_KEY" = "1" ]; then
  run "${AWS[@]}" ssm delete-parameter --name "$API_KEY_PARAM"
else
  echo "  (kept $API_KEY_PARAM — pass --purge-key to delete)"
fi

echo "== done (apply=$APPLY) =="
