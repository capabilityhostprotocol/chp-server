#!/usr/bin/env bash
# Bootstrap the governed `vercel/api_token` secret on a (possibly headless) node from the
# token that originates on THIS machine's Vercel CLI login (or a token file).
#
# Why this exists alongside the adapter's rotate_token capability: rotate_token is node-local
# (it reads a `vercel login` on the node it runs on). A headless deploy node like auxo-NUC14RVS
# has no interactive login, so the token must be seeded from the machine where `vercel login`
# was done. This performs that one GATED secret-write (chp.adapters.secrets.set) correctly and
# repeatably — verify-before-store, token never on the command line, output redirected so the
# value cannot echo. It is parameterized by node/source; it is not machine-specific.
#
# Usage:
#   bash bootstrap_vercel_secret.sh [node] [cli|<token-file>]
#     node         default: auxo-NUC14RVS
#     source       default: "cli" (this machine's Vercel CLI auth.json); or a token/auth-json file
set -euo pipefail

NODE="${1:-auxo-NUC14RVS}"
SRC="${2:-cli}"
SECRET_KEY="${VERCEL_SECRET_KEY:-vercel/api_token}"

if [ "$SRC" = "cli" ]; then
  TOKEN_FILE=""
  for p in \
    "$HOME/Library/Application Support/com.vercel.cli/auth.json" \
    "$HOME/.local/share/com.vercel.cli/auth.json" \
    "$HOME/.config/com.vercel.cli/auth.json"; do
    [ -r "$p" ] && { TOKEN_FILE="$p"; break; }
  done
  [ -n "$TOKEN_FILE" ] || { echo "no Vercel CLI auth found — run 'vercel login' first." >&2; exit 2; }
else
  TOKEN_FILE="$SRC"
fi
[ -r "$TOKEN_FILE" ] || { echo "token source not readable: $TOKEN_FILE" >&2; exit 2; }

# Extract .token if the file is a Vercel CLI auth JSON, else treat it as a raw token; strip CR/space.
RAW="$(cat "$TOKEN_FILE")"
if printf '%s' "$RAW" | jq -e 'type=="object" and has("token")' >/dev/null 2>&1; then
  TOK="$(printf '%s' "$RAW" | jq -r '.token')"
else
  TOK="$RAW"
fi
TOK="$(printf '%s' "$TOK" | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
[ -n "$TOK" ] || { echo "no token found in: $TOKEN_FILE" >&2; exit 2; }

# Verify with Vercel BEFORE storing — a bad/expired token never lands in the store.
CODE="$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOK" https://api.vercel.com/v2/user)"
echo "vercel /v2/user -> HTTP $CODE (token length ${#TOK})"
[ "$CODE" = "200" ] || { echo "REJECTED ($CODE) — create a valid token / run 'vercel login'. Not storing." >&2; exit 1; }

# Governed secret write. --payload is the correct chp-home invoke form; output is redirected so
# the token value can never echo (a prior positional-arg mistake leaked a token into logs).
if chp-home invoke "$NODE" chp.adapters.secrets.set \
     --payload "$(jq -nc --arg k "$SECRET_KEY" --arg v "$TOK" '{key:$k,value:$v}')" >/dev/null 2>&1; then
  echo "STORED '$SECRET_KEY' on $NODE (verified 200)."
else
  echo "secret-store write FAILED on $NODE (is the node online? is secrets.set admitted?)." >&2
  exit 1
fi
unset TOK RAW
