#!/bin/bash
# deploy.sh — Push latest code to DigitalOcean and restart the bot
# Usage: ./deploy.sh
# Run from your Mac inside the linkedin_manager folder.

set -e

DROPLET_IP="162.243.248.247"
REMOTE_USER="root"
REMOTE_DIR="/root/linkedin_manager"

# SSH multiplexing — asks for passphrase ONCE and reuses the connection
SOCKET="/tmp/deploy_ssh_socket"
SSH_OPTS="-o StrictHostKeyChecking=no -o ControlMaster=auto -o ControlPath=${SOCKET} -o ControlPersist=60"
SSH="ssh ${SSH_OPTS} ${REMOTE_USER}@${DROPLET_IP}"
SCP="scp ${SSH_OPTS}"

echo "🚀 Deploying LinkedIn Manager to $DROPLET_IP..."
echo ""

# Open the shared SSH connection (passphrase entered once here)
echo "🔑 Connecting (enter passphrase once)..."
ssh ${SSH_OPTS} -o ControlMaster=yes -fN ${REMOTE_USER}@${DROPLET_IP}

# ── 1. Create remote directory if it doesn't exist
$SSH "mkdir -p ${REMOTE_DIR}/data/media ${REMOTE_DIR}/data/logs"

# ── 2. Copy ALL project files (including Docker config)
echo ""
echo "📦 Copying files..."
$SCP \
  discord_bot.py \
  config.py \
  scheduler.py \
  linkedin.py \
  rewriter.py \
  database.py \
  main.py \
  oauth_setup.py \
  requirements.txt \
  Dockerfile \
  docker-compose.yml \
  test_mock.py \
  "${REMOTE_USER}@${DROPLET_IP}:${REMOTE_DIR}/"

# Copy .env only if it doesn't already exist on the server
# (avoids overwriting tokens that were set up there)
ENV_EXISTS=$($SSH "[ -f ${REMOTE_DIR}/.env ] && echo yes || echo no")
if [ "$ENV_EXISTS" = "no" ]; then
  echo "   📋 .env not found on server — copying local .env..."
  $SCP .env "${REMOTE_USER}@${DROPLET_IP}:${REMOTE_DIR}/.env"
else
  echo "   ✅ .env already exists on server (not overwriting)"
fi

echo "   ✅ Files copied"

# ── 3. Rebuild and restart the container
echo ""
echo "🐳 Rebuilding Docker container..."
$SSH "cd ${REMOTE_DIR} && docker compose down; docker compose up -d --build"

echo ""
echo "⏳ Waiting for bot to start..."
sleep 10

# ── 4. Show logs to confirm it's running
echo ""
echo "📋 Bot logs (last 30 lines):"
echo "─────────────────────────────────────────"
$SSH "docker logs linkedin_manager --tail 30 2>&1"
echo "─────────────────────────────────────────"
echo ""
echo "✅ Deploy complete."
echo "   You should see 'Discord bot ready' in the logs above."
echo ""
echo "   To watch live logs:"
echo "   ssh ${REMOTE_USER}@${DROPLET_IP} 'docker logs linkedin_manager -f'"

# Close the shared connection
ssh ${SSH_OPTS} -O exit ${REMOTE_USER}@${DROPLET_IP} 2>/dev/null || true
