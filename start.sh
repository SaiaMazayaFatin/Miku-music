#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAVALINK_JAR="${ROOT_DIR}/lavalink/Lavalink.jar"
LAVALINK_CONFIG="${ROOT_DIR}/lavalink/application.yml"

if [[ ! -f "${LAVALINK_JAR}" ]]; then
  echo "[ERROR] Lavalink.jar not found at ${LAVALINK_JAR}"
  exit 1
fi

if [[ ! -f "${LAVALINK_CONFIG}" ]]; then
  echo "[ERROR] application.yml not found at ${LAVALINK_CONFIG}"
  exit 1
fi

echo "[BOOT] Starting Lavalink..."
java -jar "${LAVALINK_JAR}" --spring.config.location="file:${LAVALINK_CONFIG}" &
LAVALINK_PID=$!

shutdown() {
  echo "[BOOT] Shutting down Lavalink (${LAVALINK_PID})"
  kill "${LAVALINK_PID}" 2>/dev/null || true
}

trap shutdown EXIT INT TERM

echo "[BOOT] Waiting for Lavalink to listen on 127.0.0.1:2333..."
READY=0
for _ in $(seq 1 60); do
  if (echo > /dev/tcp/127.0.0.1/2333) >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done

if [[ "${READY}" -ne 1 ]]; then
  echo "[ERROR] Lavalink did not become ready in time"
  exit 1
fi

echo "[BOOT] Starting Discord bot..."
python3 "${ROOT_DIR}/bot.py"
