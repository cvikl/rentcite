#!/usr/bin/env bash
# Publish Homerule to the shared Hetzner box -> https://homerule.ruleandrecord.com
#   bash deploy/publish.sh
# Same conventions as the other services (see ../../infra/README.md): app in /opt/homerule, container on the existing
# Caddy network, Caddy drop-in in /opt/caddy-sites, zero-downtime `caddy reload`. Touches nothing else on the box.
# Requires a DNS A record for homerule.ruleandrecord.com pointing at the box (Cloudflare, DNS-only).
set -euo pipefail
HOST=${SERVER:-root@37.27.202.168}
APP_DIR=/opt/homerule
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -f "$ROOT/deploy/.env" ]; then
  if [ -f "$ROOT/.env" ]; then cp "$ROOT/.env" "$ROOT/deploy/.env"; else cp "$ROOT/.env.example" "$ROOT/deploy/.env"; fi
fi

echo "==> rsync sources to $HOST:$APP_DIR"
ssh "$HOST" "mkdir -p $APP_DIR /opt/caddy-sites"
rsync -az --delete --exclude .env --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude .git --exclude .impeccable \
  "$ROOT/app" "$ROOT/static" "$ROOT/data" "$ROOT/out" "$ROOT/cache" "$ROOT/deploy" "$ROOT/requirements.txt" "$ROOT/README.md" "$HOST:$APP_DIR/"
scp -q "$ROOT/deploy/.env" "$HOST:$APP_DIR/deploy/.env"
ssh "$HOST" "chmod 600 $APP_DIR/deploy/.env"

echo "==> build + start"
ssh "$HOST" "cd $APP_DIR/deploy && docker compose build homerule && docker compose up -d homerule"
# the outputs and cache live in volumes so 'Add a law' survives restarts; seed them from the image on first start
ssh "$HOST" "cd $APP_DIR/deploy && docker compose exec -T homerule sh -c 'ls out/rules.json >/dev/null 2>&1 || true'"

echo "==> caddy drop-in + reload"
rsync -az "$ROOT/deploy/homerule.caddy" "$HOST:/opt/caddy-sites/homerule.caddy"
ssh "$HOST" "cd /opt/compass/deploy && docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile"

echo "==> health"
sleep 3
ssh "$HOST" "curl -sf http://127.0.0.1:8795/api/health && echo"
curl -sS -o /dev/null -w "https://homerule.ruleandrecord.com  HTTP %{http_code}\n" --max-time 30 https://homerule.ruleandrecord.com/ || echo "  (first HTTPS hit may lag while Let's Encrypt issues the cert)"
