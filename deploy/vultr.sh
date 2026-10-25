#!/usr/bin/env bash
# Deploy ChillySOS (planner page + iPhone API) to a fresh Vultr Ubuntu 24.04 server, with HTTPS from Caddy.
#
#   deploy/vultr.sh <server IP> [hostname]
#
# hostname defaults to <ip-with-dashes>.sslip.io, a public DNS name that points at the IP, so Caddy can get a
# Let's Encrypt certificate without a domain. Point your domain's A records (root and www) at the
# IP and pass the domain to use it instead (chillysos.us is on Porkbun);
# the sslip.io name keeps working too. Re-run any time to push new code; the server keeps its databases.
#
# Needs: the SSH key ~/.ssh/swelter_vultr added to the server, and a filled-in .env (copied to the server).
set -euo pipefail
IP=${1:?usage: deploy/vultr.sh <server IP> [hostname]}
SSLIP=${IP//./-}.sslip.io
HOSTNAME_=${2:-$SSLIP}
# Your own domain also gets www.<domain> redirected to it (point both A records at the IP).
SITES=$HOSTNAME_; WWW=""
[ "$HOSTNAME_" != "$SSLIP" ] && SITES="$HOSTNAME_, $SSLIP" && WWW="www.$HOSTNAME_ {
  redir https://$HOSTNAME_{uri} permanent
}"
KEY=~/.ssh/swelter_vultr
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new root@$IP"
ROOT=$(cd "$(dirname "$0")/.." && pwd)

echo "== ChillySOS -> $IP as https://$HOSTNAME_"
$SSH 'command -v caddy >/dev/null || (apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq caddy rsync >/dev/null)
      command -v /root/.local/bin/uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
      mkdir -p /srv/swelter'

rsync -az --delete -e "ssh -i $KEY" \
  --exclude .git --exclude .venv --exclude .venv-ml --exclude ios --exclude 'data/raw' --exclude 'data/*.db*' \
  --exclude 'data/tts' --exclude models --exclude scripts --exclude .claude --exclude node_modules \
  --exclude '__pycache__' --exclude .env \
  "$ROOT/" "root@$IP:/srv/swelter/"
scp -q -i "$KEY" "$ROOT/.env" "root@$IP:/srv/swelter/.env"

$SSH "cat > /etc/systemd/system/swelter.service <<'UNIT'
[Unit]
Description=ChillySOS server
After=network-online.target

[Service]
WorkingDirectory=/srv/swelter
Environment=HOST=127.0.0.1 PORT=8000 SWELTER_DEV_LOGIN=1
ExecStart=/root/.local/bin/uv run --env-file .env --extra tiger server.py
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/caddy/Caddyfile <<CADDY
$SITES {
  encode gzip
  reverse_proxy 127.0.0.1:8000
}
$WWW
CADDY
ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw --force enable >/dev/null
systemctl daemon-reload && systemctl enable --now swelter >/dev/null 2>&1 && systemctl restart swelter caddy"

echo "== waiting for https://$HOSTNAME_ ..."
for _ in $(seq 60); do curl -fsS "https://$HOSTNAME_/api/status" >/dev/null 2>&1 && break; sleep 3; done
curl -fsS "https://$HOSTNAME_/api/config" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("auth0:", d["auth0"]["enabled"], "| db:", d["db"], "| ask:", d["ask"], "| voice:", d["voice"])'
echo "== live: https://$HOSTNAME_/"
