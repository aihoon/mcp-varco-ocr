#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-usage}"
HOST_LOG_DIR="/home/aihoon/Workspace/mcp-varco-ocr/logs"

if [[ "${MODE}" == "rest" ]]; then
  SERVICE_NAME="varco-ocr-rest"
  ENDPOINT="http://127.0.0.1:8765"
elif [[ "${MODE}" == "mcp-http" ]]; then
  SERVICE_NAME="varco-ocr-mcp"
  ENDPOINT="http://127.0.0.1:8766/mcp"
else
  echo
  echo "Usage: $0 [rest|mcp-http]"
  echo
  exit 1
fi

echo "[1/4] Moving to project root: ${PROJECT_ROOT}"
cd "${PROJECT_ROOT}"

echo "[2/4] Starting compose service: ${SERVICE_NAME}"
export HOST_LOG_DIR
docker compose up -d --build "${SERVICE_NAME}"

echo "[3/4] Done"
echo "Mode     : ${MODE}"
echo "Service  : ${SERVICE_NAME}"
echo "Endpoint : ${ENDPOINT}"
echo "Logs     : ${HOST_LOG_DIR}/server.log"
echo
echo "Useful commands:"
echo "  docker compose ps"
echo "  docker compose logs -f ${SERVICE_NAME}"
echo "  docker compose down"
echo "  tail -f ${HOST_LOG_DIR}/server.log"
