#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT=/home/ubuntu/personal-ai
CODEX_BIN=/home/ubuntu/.local/bin/codex
source "${DEPLOY_ROOT}/versions.lock"

VERIFY_FAILURES=0

report_expected() {
  local label=$1
  local actual=$2
  local expected=$3
  printf '%s=%s\n' "${label}" "${actual}"
  if [[ "${actual}" != "${expected}" ]]; then
    printf 'verification_error=%s expected %s, got %s\n' \
      "${label}" "${expected}" "${actual}" >&2
    VERIFY_FAILURES=$((VERIFY_FAILURES + 1))
  fi
}

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

report_expected \
  astrbot_active \
  "$(systemctl is-active astrbot.service 2>/dev/null || true)" \
  active
report_expected \
  astrbot_enabled \
  "$(systemctl is-enabled astrbot.service 2>/dev/null || true)" \
  enabled
report_expected \
  astrbot_user \
  "$(systemctl show astrbot.service -p User --value 2>/dev/null || true)" \
  ubuntu
report_expected \
  astrbot_restart_policy \
  "$(systemctl show astrbot.service -p Restart --value 2>/dev/null || true)" \
  on-failure
report_expected \
  napcat_running \
  "$(docker inspect -f '{{.State.Running}}' personal-ai-napcat 2>/dev/null || false)" \
  true
report_expected \
  napcat_restart_policy \
  "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' personal-ai-napcat 2>/dev/null || true)" \
  unless-stopped
report_expected \
  openviking_restart_policy \
  "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' personal-ai-openviking 2>/dev/null || true)" \
  unless-stopped
report_expected \
  ollama_restart_policy \
  "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' personal-ai-ollama 2>/dev/null || true)" \
  unless-stopped

OPENVIKING_HEALTH=$(curl --fail --silent http://127.0.0.1:1933/health | jq -r '.healthy // false')
report_expected openviking_health "${OPENVIKING_HEALTH}" true

CODEX_VERSION=$("${CODEX_BIN}" --version 2>/dev/null || true)
report_expected codex_version "${CODEX_VERSION}" "codex-cli ${CODEX_TESTED_VERSION}"

CODEX_LOGGED_IN=false
if "${CODEX_BIN}" login status 2>&1 | grep -q 'Logged in'; then
  CODEX_LOGGED_IN=true
fi
report_expected codex_logged_in "${CODEX_LOGGED_IN}" true

ASTRBOT_LOCAL_LISTENER=false
if listener_present '127.0.0.1:6185'; then
  ASTRBOT_LOCAL_LISTENER=true
fi
report_expected astrbot_local_listener "${ASTRBOT_LOCAL_LISTENER}" true

NAPCAT_LOCAL_LISTENER=false
if listener_present '127.0.0.1:6099'; then
  NAPCAT_LOCAL_LISTENER=true
fi
report_expected napcat_local_listener "${NAPCAT_LOCAL_LISTENER}" true

OPENVIKING_LOCAL_LISTENER=false
if listener_present '127.0.0.1:1933'; then
  OPENVIKING_LOCAL_LISTENER=true
fi
report_expected openviking_local_listener "${OPENVIKING_LOCAL_LISTENER}" true

ONEBOT_BRIDGE_LISTENER=false
if listener_present '172.30.0.1:6199'; then
  ONEBOT_BRIDGE_LISTENER=true
fi
report_expected onebot_bridge_listener "${ONEBOT_BRIDGE_LISTENER}" true

PUBLIC_NON_SSH_TCP_LISTENERS=$(ss -lntH | awk '
  ($4 ~ /^0\.0\.0\.0:/ || $4 ~ /^\[::\]:/ || $4 ~ /^\*:/) &&
  ($4 !~ /:22$/) {count++}
  END {print count+0}')
report_expected \
  public_non_ssh_tcp_listeners \
  "${PUBLIC_NON_SSH_TCP_LISTENERS}" \
  0

UFW_STATUS=$(sudo ufw status 2>/dev/null | awk 'NR == 1 {print tolower($2)}')
printf 'ufw_status=%s\n' "${UFW_STATUS:-unavailable}"

report_expected \
  codex_auth_link \
  "$(readlink "${DEPLOY_ROOT}/astrbot/codex-home/auth.json" 2>/dev/null || true)" \
  /home/ubuntu/.codex/auth.json
report_expected \
  plugin_source_link \
  "$(readlink "${DEPLOY_ROOT}/astrbot/data/plugins/astrbot_plugin_codex_bridge" 2>/dev/null || true)" \
  "${DEPLOY_ROOT}/plugins/astrbot_plugin_codex_bridge"

for private_file in \
  "${DEPLOY_ROOT}/astrbot/secrets/codex-bridge.env" \
  "${DEPLOY_ROOT}/napcat/secrets/onebot.token"; do
  report_expected \
    "private_mode_$(basename "${private_file}" | tr '.-' '__')" \
    "$(stat -c '%a' "${private_file}" 2>/dev/null || true)" \
    600
done

free -h | awk '/^Mem:/ {print "memory_used=" $3 ",memory_available=" $7} /^Swap:/ {print "swap_used=" $3 ",swap_total=" $2}'
docker stats --no-stream --format '{{.Name}} memory={{.MemUsage}} cpu={{.CPUPerc}}' \
  personal-ai-openviking personal-ai-ollama personal-ai-napcat 2>/dev/null || true

PYTHONPATH="${DEPLOY_ROOT}/plugins" \
  "${DEPLOY_ROOT}/astrbot/uv-tools/astrbot/bin/python" -m unittest discover \
  -s "${DEPLOY_ROOT}/plugins/astrbot_plugin_codex_bridge/tests" \
  -p 'test_*.py' >/dev/null
echo 'plugin_unit_tests=true'

if ((VERIFY_FAILURES > 0)); then
  printf 'verification_passed=false failures=%s\n' "${VERIFY_FAILURES}" >&2
  exit 1
fi
echo 'verification_passed=true'
