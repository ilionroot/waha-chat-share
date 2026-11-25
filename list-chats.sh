#!/usr/bin/env bash
# Lista os chats da sessão para escolher o CHAT_ID.
set -euo pipefail
cd "$(dirname "$0")"
KEY=$(grep '^WAHA_API_KEY=' .env | cut -d= -f2-)
curl -s -H "X-Api-Key: $KEY" "http://127.0.0.1:3000/api/default/chats?limit=${1:-30}" \
  | python3 -c 'import json,sys; [print(c["id"]["_serialized"] if isinstance(c["id"], dict) else c["id"], "|", c.get("name") or "") for c in json.load(sys.stdin)]'
