#!/bin/bash
set -e
echo "=== PumpDesk Deploy ==="
cd /home/ubuntu/pumpdesk
git pull
docker compose down
docker compose up -d --build
echo "=== Deploy complete ==="
docker compose ps

