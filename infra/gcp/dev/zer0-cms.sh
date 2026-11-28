#!/usr/bin/env bash
# ============================================================================
# infra/gcp/dev/zer0-cms.sh — runs ON the development instance, as the
# operator, sent there by up.sh. It brings up zer0-CMS's DEVELOPMENT stack
# (its own `docker compose --profile content`: the app, a worker, the
# scheduler, the relay, two consumers, Postgres with pgvector and Redis), bound
# to the machine's loopback only. Safe to run again: it updates and restarts.
#
# Development, not production: made-up content, a database with no backup, and
# sign-in codes printed to the app's log instead of emailed. Never client data.
# ============================================================================
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

REPO_URL="${ZER0_CMS_REPO:-https://github.com/bamr87/zer0-CMS.git}"
REPO_DIR="$HOME/dev/zer0-cms"

if ! command -v docker >/dev/null 2>&1 || ! sudo docker compose version >/dev/null 2>&1; then
  echo "dev: installing Docker from the distribution's packages"
  sudo apt-get update -qq
  sudo apt-get install -y -qq --no-install-recommends docker.io docker-compose docker-buildx git curl ca-certificates openssl
fi
sudo systemctl enable --now docker >/dev/null

mkdir -p "$(dirname "$REPO_DIR")"
if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" pull --ff-only --quiet
else
  git clone --quiet --depth 1 "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

# Generated here, once, and never leaves the machine.
if [[ ! -f .env ]]; then
  (umask 077; printf 'CONTENT_SECRET_KEY=%s\nPOSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)" "$(openssl rand -hex 16)" > .env)
fi

# Development only: a sign-in code is written to the app's log, not emailed,
# because this instance has no email sender.
cat > docker-compose.override.yml <<'OVERRIDE'
services:
  content:
    environment:
      EMAIL_BACKEND: django.core.mail.backends.console.EmailBackend
  worker:
    environment:
      EMAIL_BACKEND: django.core.mail.backends.console.EmailBackend
OVERRIDE

echo "dev: building and starting zer0-CMS (the first build takes several minutes)"
sudo docker compose --profile content up -d --build --quiet-pull

echo "dev: waiting for /readyz"
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8000/readyz >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
curl -fsS http://127.0.0.1:8000/readyz && echo
curl -fsS http://127.0.0.1:8000/version && echo
echo "dev: zer0-CMS answers on this machine's loopback, port 8000"
