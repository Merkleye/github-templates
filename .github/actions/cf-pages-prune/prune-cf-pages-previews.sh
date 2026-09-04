#!/usr/bin/env bash
set -euo pipefail

# Deletes Cloudflare Pages preview-environment deployments, either:
#   --branch <name>        all preview deployments for an exact branch alias
#   --max-age-days <n>     all preview deployments older than n days
#
# Requires env: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, PROJECT_NAME
#
# Only ever touches deployments whose environment is "preview" — production
# deployments are filtered out in the jq selector below and can never be
# deleted by this script, whatever arguments it is handed.

BRANCH=""
MAX_AGE_DAYS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch) BRANCH="$2"; shift 2 ;;
    --max-age-days) MAX_AGE_DAYS="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$BRANCH" && -z "$MAX_AGE_DAYS" ]]; then
  echo "Must pass --branch or --max-age-days" >&2
  exit 1
fi

: "${CLOUDFLARE_API_TOKEN:?}"
: "${CLOUDFLARE_ACCOUNT_ID:?}"
: "${PROJECT_NAME:?}"

api="https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/pages/projects/${PROJECT_NAME}/deployments"
cutoff_epoch=""
if [[ -n "$MAX_AGE_DAYS" ]]; then
  cutoff_epoch=$(date -u -d "-${MAX_AGE_DAYS} days" +%s)
fi

page=1
deleted=0
while :; do
  response=$(curl -sS -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" "${api}?page=${page}&per_page=25")

  count=$(jq '.result | length' <<<"$response")
  [[ "$count" -eq 0 ]] && break

  ids=$(jq -r --arg branch "$BRANCH" --arg cutoff "$cutoff_epoch" '
    .result[]
    | select(.environment == "preview")
    | select($branch == "" or .deployment_trigger.metadata.branch == $branch)
    | select($cutoff == "" or ((.created_on | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601) < ($cutoff | tonumber)))
    | .id
  ' <<<"$response")

  for id in $ids; do
    echo "Deleting preview deployment ${id}"
    curl -sS -X DELETE -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" "${api}/${id}?force=true" >/dev/null
    deleted=$((deleted + 1))
  done

  total_pages=$(jq -r '.result_info.total_pages // 1' <<<"$response")
  [[ "$page" -ge "$total_pages" ]] && break
  page=$((page + 1))
done

echo "Deleted ${deleted} preview deployment(s)."
