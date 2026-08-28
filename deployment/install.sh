#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT=/home/ubuntu/personal-ai
ASTRBOT_ROOT=${DEPLOY_ROOT}/astrbot
NAPCAT_ROOT=${DEPLOY_ROOT}/napcat
CODEX_BIN=/home/ubuntu/.local/bin/codex

if [[ $(id -un) != ubuntu ]]; then
  echo "Run this installer as ubuntu (passwordless sudo is expected)." >&2
  exit 1
fi

source "${DEPLOY_ROOT}/versions.lock"
umask 077

command -v docker >/dev/null
docker compose version >/dev/null
test -x "${CODEX_BIN}"
"${CODEX_BIN}" login status >/dev/null

install -d -m 700 \
  "${ASTRBOT_ROOT}" \
  "${ASTRBOT_ROOT}/backups" \
  "${ASTRBOT_ROOT}/codex-home" \
  "${ASTRBOT_ROOT}/data/plugins" \
  "${ASTRBOT_ROOT}/secrets" \
  "${DEPLOY_ROOT}/agent-workspace" \
  "${NAPCAT_ROOT}/backups" \
  "${NAPCAT_ROOT}/config" \
  "${NAPCAT_ROOT}/data" \
  "${NAPCAT_ROOT}/logs" \
  "${NAPCAT_ROOT}/plugins" \
  "${NAPCAT_ROOT}/qq" \
  "${NAPCAT_ROOT}/secrets"

if [[ ! -r /home/ubuntu/.codex/auth.json ]]; then
  echo "Codex ChatGPT login is unavailable." >&2
  exit 1
fi
ln -sfn /home/ubuntu/.codex/auth.json "${ASTRBOT_ROOT}/codex-home/auth.json"

if [[ ! -x "${ASTRBOT_ROOT}/.tools/uv" ]]; then
  UV_INSTALL_SCRIPT=$(mktemp /tmp/astrbot-uv-install.XXXXXX)
  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
    "https://astral.sh/uv/${UV_VERSION}/install.sh" -o "${UV_INSTALL_SCRIPT}"
  env UV_INSTALL_DIR="${ASTRBOT_ROOT}/.tools" sh "${UV_INSTALL_SCRIPT}"
  rm -f "${UV_INSTALL_SCRIPT}"
fi

UV_TOOL_DIR="${ASTRBOT_ROOT}/uv-tools" \
UV_TOOL_BIN_DIR="${ASTRBOT_ROOT}/bin" \
UV_PYTHON_INSTALL_DIR="${ASTRBOT_ROOT}/python" \
UV_CACHE_DIR="${ASTRBOT_ROOT}/.uv-cache" \
  "${ASTRBOT_ROOT}/.tools/uv" tool install \
  --python "${PYTHON_VERSION}" --managed-python "astrbot==${ASTRBOT_VERSION}"

git -C "${DEPLOY_ROOT}/agent-workspace" init -q
ln -sfn "${DEPLOY_ROOT}/plugins/astrbot_plugin_codex_bridge" \
  "${ASTRBOT_ROOT}/data/plugins/astrbot_plugin_codex_bridge"

if [[ ! -s "${NAPCAT_ROOT}/secrets/onebot.token" ]]; then
  openssl rand -hex 32 >"${NAPCAT_ROOT}/secrets/onebot.token"
fi
chmod 600 "${NAPCAT_ROOT}/secrets/onebot.token"
if [[ ! -e "${NAPCAT_ROOT}/secrets/napcat.env" ]]; then
  printf 'ACCOUNT=\n' >"${NAPCAT_ROOT}/secrets/napcat.env"
fi
chmod 600 "${NAPCAT_ROOT}/secrets/napcat.env"

sudo install -o root -g root -m 0644 \
  "${DEPLOY_ROOT}/deployment/systemd/astrbot.service" \
  /etc/systemd/system/astrbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now astrbot.service
docker compose -f "${NAPCAT_ROOT}/compose.yaml" up -d

if [[ -e "${DEPLOY_ROOT}/openviking/data/ov.conf" ]]; then
  sudo /usr/bin/python3 "${DEPLOY_ROOT}/deployment/provision_openviking_bridge.py" \
    --ov-config "${DEPLOY_ROOT}/openviking/data/ov.conf" \
    --env-file "${ASTRBOT_ROOT}/secrets/codex-bridge.env" \
    --owner-uid "$(id -u)" --owner-gid "$(id -g)"
  sudo systemctl restart astrbot.service
else
  echo "OpenViking configuration was not found; provision memory after restoring it."
fi

echo "Base deployment installed. Complete QQ QR login, then run deployment/finalize_after_qq_login.sh."
