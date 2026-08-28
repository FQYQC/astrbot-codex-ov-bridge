#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT=/home/ubuntu/personal-ai
CODEX_BIN=/home/ubuntu/.local/bin/codex

listener_present() {
  local listener_address=$1
  ss -lntH | awk -v target="${listener_address}" \
    '$4 == target {found=1} END {exit !found}'
}

# AstrBot binds WebUI and OneBot after the systemd unit is already active.
# Give all expected listeners a short shared startup window before reporting.
for verify_attempt in $(seq 1 20); do
  if listener_present '127.0.0.1:6185' \
    && listener_present '127.0.0.1:6099' \
    && listener_present '172.30.0.1:6199'; then
    break
  fi
  sleep 1
done

printf 'astrbot_active=%s\n' "$(systemctl is-active astrbot.service 2>/dev/null || true)"
printf 'astrbot_enabled=%s\n' "$(systemctl is-enabled astrbot.service 2>/dev/null || true)"
printf 'napcat_running=%s\n' "$(docker inspect -f '{{.State.Running}}' personal-ai-napcat 2>/dev/null || false)"
printf 'openviking_health='
curl --fail --silent http://127.0.0.1:1933/health | jq -r '.healthy // false'
printf 'codex_version='
"${CODEX_BIN}" --version 2>/dev/null
printf 'codex_logged_in='
if "${CODEX_BIN}" login status 2>&1 | grep -q 'Logged in'; then
  echo true
else
  echo false
fi

printf 'astrbot_local_listener='
if listener_present '127.0.0.1:6185'; then
  echo true
else
  echo false
fi
printf 'napcat_local_listener='
if listener_present '127.0.0.1:6099'; then
  echo true
else
  echo false
fi
printf 'onebot_bridge_listener='
if listener_present '172.30.0.1:6199'; then
  echo true
else
  echo false
fi
printf 'public_non_ssh_tcp_listeners='
ss -lntH | awk '
  ($4 ~ /^0\.0\.0\.0:/ || $4 ~ /^\[::\]:/ || $4 ~ /^\*:/) &&
  ($4 !~ /:22$/) {count++}
  END {print count+0}'

free -h | awk '/^Mem:/ {print "memory_used=" $3 ",memory_available=" $7} /^Swap:/ {print "swap_used=" $3 ",swap_total=" $2}'
docker stats --no-stream --format '{{.Name}} memory={{.MemUsage}} cpu={{.CPUPerc}}' \
  personal-ai-openviking personal-ai-ollama personal-ai-napcat 2>/dev/null || true

PYTHONPATH="${DEPLOY_ROOT}/plugins" \
  "${DEPLOY_ROOT}/astrbot/uv-tools/astrbot/bin/python" -m unittest discover \
  -s "${DEPLOY_ROOT}/plugins/astrbot_plugin_codex_bridge/tests" \
  -p 'test_*.py' >/dev/null
echo 'plugin_unit_tests=true'
