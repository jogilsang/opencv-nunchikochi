#!/usr/bin/env bash
# Deploy the nunchikochi stack in ONE command. OWNER: cloud tab.
#
# Steps: package Lambda zip -> upload to a code bucket -> ensure SSM SecureString api key
# exists -> create/update CloudFormation stack -> upload web static -> write web/config.json
# with apiBase from stack outputs (api key is NOT written to the file; printed as guidance).
#
# C2 is author + static validation only. Run with --dry-run (DEFAULT) to print every
# mutating command without executing. Pass --apply to actually deploy (that is C3).
#
# Usage:
#   cloud/deploy.sh [--apply] [--profile captain] [--region us-east-1] [--stack nunchi] [--budget-email you@example.com]
set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE=captain REGION=us-east-1 STACK=nunchi APPLY=0 BUDGET_EMAIL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --dry-run) APPLY=0 ;;
    --profile) PROFILE="$2"; shift ;;
    --region) REGION="$2"; shift ;;
    --stack) STACK="$2"; shift ;;
    --budget-email) BUDGET_EMAIL="$2"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

AWS=(aws --profile "$PROFILE" --region "$REGION")
ACCOUNT=$("${AWS[@]}" sts get-caller-identity --query Account --output text 2>/dev/null || echo ACCOUNT)
# Never print the raw account id to logs; show a masked suffix only.
ACCOUNT_MASK="***${ACCOUNT: -4}"
CODE_BUCKET="${STACK}-code-${ACCOUNT}"
CODE_BUCKET_MASK="${STACK}-code-${ACCOUNT_MASK}"
ZIP="cloud/build/nunchi-service.zip"
KEY="lambda/nunchi-service.zip"
API_KEY_PARAM="/nunchi/api-key"
IP_SALT_PARAM="/nunchi/ip-salt"

run() {  # echo always (account id masked); execute only when --apply
  local shown="$*"
  shown="${shown//$ACCOUNT/$ACCOUNT_MASK}"
  echo "  \$ $shown"
  if [ "$APPLY" = "1" ]; then "$@"; fi
}

echo "== nunchikochi deploy (apply=$APPLY, profile=$PROFILE, region=$REGION, stack=$STACK) =="
echo "[1/6] identity (read-only)"
"${AWS[@]}" sts get-caller-identity --query Arn --output text >/dev/null \
  && echo "  caller: profile=$PROFILE account=$ACCOUNT_MASK (verified)" \
  || { echo "  ERROR: cannot verify identity for profile $PROFILE" >&2; exit 1; }

echo "[2/6] package Lambda zip (arm64)"
run bash cloud/package.sh "$ZIP"

echo "[3/6] ensure code bucket + upload zip  (bucket: $CODE_BUCKET_MASK)"
run "${AWS[@]}" s3api head-bucket --bucket "$CODE_BUCKET" ||
  run "${AWS[@]}" s3api create-bucket --bucket "$CODE_BUCKET"
run "${AWS[@]}" s3 cp "$ZIP" "s3://$CODE_BUCKET/$KEY"

echo "[4/6] ensure SSM SecureStrings ($API_KEY_PARAM, $IP_SALT_PARAM) — values never printed"
echo "  (create once, out-of-band, if absent:)"
echo "  \$ ${AWS[*]} ssm put-parameter --name $API_KEY_PARAM --type SecureString --value \"\$(openssl rand -hex 24)\" --no-overwrite"
echo "  \$ ${AWS[*]} ssm put-parameter --name $IP_SALT_PARAM --type SecureString --value \"\$(openssl rand -hex 32)\" --no-overwrite"
if [ "$APPLY" = "1" ]; then
  "${AWS[@]}" ssm get-parameter --name "$API_KEY_PARAM" >/dev/null 2>&1 ||
    "${AWS[@]}" ssm put-parameter --name "$API_KEY_PARAM" --type SecureString \
      --value "$(openssl rand -hex 24)" --no-overwrite >/dev/null
  # C17: HMAC salt for IP hashing (trial-key per-IP daily limit). Random if absent; the
  # value is never printed. Only the hash of an IP is ever stored.
  "${AWS[@]}" ssm get-parameter --name "$IP_SALT_PARAM" >/dev/null 2>&1 ||
    "${AWS[@]}" ssm put-parameter --name "$IP_SALT_PARAM" --type SecureString \
      --value "$(openssl rand -hex 32)" --no-overwrite >/dev/null
fi

echo "[5/6] deploy stack (change-set based, create or update)"
BUDGET_ARG=""
[ -n "$BUDGET_EMAIL" ] && BUDGET_ARG="BudgetEmail=$BUDGET_EMAIL"
run "${AWS[@]}" cloudformation deploy \
  --stack-name "$STACK" \
  --template-file cloud/template.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      "Prefix=$STACK" \
      "LambdaCodeBucket=$CODE_BUCKET" \
      "LambdaCodeKey=$KEY" \
      "ApiKeyParamName=$API_KEY_PARAM" \
      "IpSaltParamName=$IP_SALT_PARAM" \
      $BUDGET_ARG \
  --tags project=nunchikochi delete-after=2026-11-30

echo "[6/6] upload web static + write web/config.json (apiBase from outputs; key NOT written)"
if [ "$APPLY" = "1" ]; then
  WEB_BUCKET=$("${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='WebBucketName'].OutputValue" --output text)
  API_BASE=$("${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='ApiBase'].OutputValue" --output text)
  "${AWS[@]}" s3 sync web/ "s3://$WEB_BUCKET/" \
    --exclude "config.json" --exclude "config.example.json" --exclude "*.md"
  # Write config.json (apiBase only, NO key) and upload it explicitly. The sync above
  # excludes config.json so a stale/committed copy never overwrites the stack value; we
  # must upload the freshly-generated one here or the web app has no service address.
  printf '{\n  "apiBase": "%s"\n}\n' "$API_BASE" > web/config.json
  "${AWS[@]}" s3 cp web/config.json "s3://$WEB_BUCKET/config.json" --content-type "application/json"
  echo "  wrote + uploaded web/config.json  apiBase=$API_BASE"
  echo "  NOTE: set the X-Api-Key in the browser/app config manually — it is in SSM ($API_KEY_PARAM), not in config.json."
else
  echo "  \$ ${AWS[*]} cloudformation describe-stacks --stack-name $STACK --query \"Stacks[0].Outputs\""
  echo "  \$ ${AWS[*]} s3 sync web/ s3://<WebBucket>/ --exclude config.json --exclude '*.md'"
  echo "  \$ ${AWS[*]} s3 cp web/config.json s3://<WebBucket>/config.json --content-type application/json"
  echo "  (config.json is written with apiBase from the ApiBase output and uploaded explicitly; X-Api-Key stays in SSM)"
fi

echo "== done (apply=$APPLY) =="
