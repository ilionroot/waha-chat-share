#!/usr/bin/env bash
# Reinicia a sessão do WAHA se ela tiver caído (FAILED) ou parado (STOPPED).
set -uo pipefail
cd "$(dirname "$0")"
KEY=$(grep '^WAHA_API_KEY=' .env | cut -d= -f2-)
STATUS=$(curl -s -m 10 -H "X-Api-Key: $KEY" http://127.0.0.1:3000/api/sessions/default \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])' 2>/dev/null) || exit 0
case "$STATUS" in
  FAILED|STOPPED)
    echo "sessão em $STATUS, reiniciando"
    curl -s -m 30 -H "X-Api-Key: $KEY" -X POST http://127.0.0.1:3000/api/sessions/default/restart >/dev/null ;;
esac
