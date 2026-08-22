#!/usr/bin/env bash
# Interactive setup for a Google OAuth client used by ytmusicapi's device-code
# flow and the YouTube Data API v3 playlist endpoints.
# Writes YTMUSIC_OAUTH_CLIENT_ID / YTMUSIC_OAUTH_CLIENT_SECRET into server/.env.
#
# Usage:
#   ./scripts/setup-google-oauth.sh              interactive setup / verify / replace
#   ./scripts/setup-google-oauth.sh --verify-only   just check existing server/.env credentials
#   ./scripts/setup-google-oauth.sh --dry-run       walk through the mechanics with placeholder
#                                                    values only; never touches the real .env
#                                                    and never contacts Google
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$SERVER_DIR/.env"
PYTHON="$SERVER_DIR/.venv/bin/python"

DRY_RUN=0
VERIFY_ONLY=0
TMP_FILES=()

cleanup() {
  local ec=$?
  for f in "${TMP_FILES[@]:-}"; do
    if [ -n "$f" ] && [ -f "$f" ]; then
      rm -f "$f"
    fi
  done
  return $ec
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

usage() {
  cat <<'EOF'
Sets up a Google OAuth client for YouTube Music playlist export via the
device-code flow and YouTube Data API v3 playlist endpoints.

Options:
  --verify-only   Check the credentials already in server/.env and exit.
  --dry-run       Demonstrate the file-write mechanics with fixed placeholder
                  values. Does not touch the real .env, does not call Google,
                  and ignores any real-looking input.
  -h, --help      Show this help.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --verify-only) VERIFY_ONLY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage; exit 1 ;;
  esac
done

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}
require_cmd grep
require_cmd awk
require_cmd mktemp

if [ "$DRY_RUN" -eq 0 ] && [ ! -x "$PYTHON" ]; then
  echo "Missing venv Python at $PYTHON (run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)" >&2
  exit 1
fi

CLIENT_ID_RE='^[0-9]+-[0-9a-zA-Z]+\.apps\.googleusercontent\.com$'

mask_secret() {
  local val="$1"
  echo "(hidden, ${#val} chars)"
}

get_env_var() {
  local file="$1" key="$2"
  [ -f "$file" ] || { echo ""; return 0; }
  grep -m1 "^${key}=" "$file" 2>/dev/null | sed "s/^${key}=//" || true
}

# Upserts KEY=VALUE in $1 by exact key match, preserving every other line untouched.
set_env_var() {
  local file="$1" key="$2" value="$3"
  local tmp
  tmp="$(mktemp)"
  TMP_FILES+=("$tmp")
  touch "$file"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} index($0,k"=")==1{print k"="v; next} {print}' "$file" > "$tmp"
  else
    cp "$file" "$tmp"
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
  fi
  mv "$tmp" "$file"
  chmod 600 "$file"
}

# Requests a device code from Google using the given client (safe, non-mutating:
# it doesn't complete auth or touch any account, just proves the client works).
# Secrets are passed via environment variables, never argv/logs.
verify_credentials() {
  local client_id="$1" client_secret="$2"
  YTMUSIC_CID="$client_id" YTMUSIC_CSEC="$client_secret" "$PYTHON" -c '
import os, sys
from ytmusicapi.auth.oauth.credentials import OAuthCredentials

creds = OAuthCredentials(client_id=os.environ["YTMUSIC_CID"], client_secret=os.environ["YTMUSIC_CSEC"])
try:
    code = creds.get_code()
    ok = bool(code.get("user_code")) and bool(code.get("verification_url"))
    sys.exit(0 if ok else 1)
except Exception:
    sys.exit(1)
' && { echo "SUCCESS"; return 0; } || { echo "FAILURE"; return 1; }
}

print_browser_steps() {
  cat <<EOF

STEP 1 — In your browser (I can't do this part for you):
  1. Go to https://console.cloud.google.com/ and log in.
  2. Create a new project (or pick an existing one) — e.g. "Audelle".
  3. Go to "APIs & Services" > "Library", search "YouTube Data API v3",
     and click "Enable". Playlist export uses its playlist-write endpoints.
  4. Go to "APIs & Services" > "OAuth consent screen".
       - User type: External is fine. Fill in app name + your email, save.
       - It's fine to leave it in "Testing" status.
       - Open "Test users" and add every Google account that will click Export.
         Accounts not listed there receive Google's 403 access_denied page.
  5. Go to "APIs & Services" > "Credentials" > "Create Credentials" >
     "OAuth client ID".
       - Application type: "TVs and Limited Input devices"
       - Name: anything, e.g. "Audelle Export"
       - Click "Create".
  6. Copy the "Client ID" (ends in .apps.googleusercontent.com) and the
     "Client Secret" shown.

EOF
}

write_and_verify() {
  local client_id="$1" client_secret="$2"

  echo "About to write to: $ENV_FILE"
  echo "  YTMUSIC_OAUTH_CLIENT_ID=$client_id"
  echo "  YTMUSIC_OAUTH_CLIENT_SECRET=$(mask_secret "$client_secret")"
  read -rp "Proceed? [y/N] " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted, nothing written."
    exit 1
  fi

  set_env_var "$ENV_FILE" "YTMUSIC_OAUTH_CLIENT_ID" "$client_id"
  set_env_var "$ENV_FILE" "YTMUSIC_OAUTH_CLIENT_SECRET" "$client_secret"
  echo "Wrote $ENV_FILE (mode 600)."

  echo "Verifying against Google's device-code endpoint..."
  if verify_credentials "$client_id" "$client_secret" >/dev/null; then
    echo "Verified: credentials work."
  else
    echo "FAILURE: Google rejected these credentials. Double check the Client ID/Secret, confirm YouTube Data API v3 is enabled on the project, and rerun this script." >&2
    exit 1
  fi
}

prompt_for_credentials() {
  local client_id client_secret
  while true; do
    read -rp "Client ID: " client_id
    if [[ "$client_id" =~ $CLIENT_ID_RE ]]; then
      break
    fi
    echo "That doesn't look like a Google OAuth Client ID (expected something ending in .apps.googleusercontent.com). Try again."
  done
  while true; do
    read -rsp "Client Secret: " client_secret
    echo
    if [ "${#client_secret}" -ge 10 ]; then
      break
    fi
    echo "That looks too short for a Google Client Secret. Try again."
  done
  write_and_verify "$client_id" "$client_secret"
}

run_dry_run() {
  echo "[dry-run] No real .env will be touched and Google will not be contacted."
  local tmp
  tmp="$(mktemp)"
  TMP_FILES+=("$tmp")
  echo "existing-unrelated-key=keep-me" > "$tmp"

  local placeholder_id="000000000000-dryrunplaceholder0000.apps.googleusercontent.com"
  local placeholder_secret="dryrunclientsecret000000000000"
  echo "[dry-run] Simulated write target: $tmp"
  echo "[dry-run] Before:"
  sed 's/^/  /' "$tmp"

  set_env_var "$tmp" "YTMUSIC_OAUTH_CLIENT_ID" "$placeholder_id"
  set_env_var "$tmp" "YTMUSIC_OAUTH_CLIENT_SECRET" "$placeholder_secret"

  echo "[dry-run] After (unrelated line preserved, keys upserted):"
  sed 's/^/  /' "$tmp"
  echo "[dry-run] Verification step is skipped (would request a device code from Google)."
  echo "[dry-run] Done. Nothing outside this temp file was touched."
}

run_verify_only() {
  local existing_id existing_secret
  existing_id="$(get_env_var "$ENV_FILE" "YTMUSIC_OAUTH_CLIENT_ID")"
  existing_secret="$(get_env_var "$ENV_FILE" "YTMUSIC_OAUTH_CLIENT_SECRET")"
  if [ -z "$existing_id" ] || [ -z "$existing_secret" ]; then
    echo "No Google OAuth credentials found in $ENV_FILE."
    exit 1
  fi
  echo "Verifying credentials in $ENV_FILE..."
  if verify_credentials "$existing_id" "$existing_secret" >/dev/null; then
    echo "SUCCESS: credentials work."
    exit 0
  else
    echo "FAILURE: Google rejected these credentials." >&2
    exit 1
  fi
}

main() {
  if [ "$DRY_RUN" -eq 1 ]; then
    run_dry_run
    exit 0
  fi

  if [ "$VERIFY_ONLY" -eq 1 ]; then
    run_verify_only
    exit 0
  fi

  local existing_id existing_secret
  existing_id="$(get_env_var "$ENV_FILE" "YTMUSIC_OAUTH_CLIENT_ID")"
  existing_secret="$(get_env_var "$ENV_FILE" "YTMUSIC_OAUTH_CLIENT_SECRET")"

  if [ -n "$existing_id" ] && [ -n "$existing_secret" ]; then
    echo "Found existing Google OAuth credentials in $ENV_FILE."
    echo "Verifying..."
    if verify_credentials "$existing_id" "$existing_secret" >/dev/null; then
      echo "They already work. Nothing to do."
      read -rp "Replace them anyway? [y/N] " replace
      if [[ ! "$replace" =~ ^[Yy]$ ]]; then
        exit 0
      fi
    else
      echo "They no longer work (revoked/rotated?). Let's replace them."
    fi
  fi

  print_browser_steps
  prompt_for_credentials
}

main
