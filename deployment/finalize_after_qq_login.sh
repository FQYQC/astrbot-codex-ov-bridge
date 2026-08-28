#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT=/home/ubuntu/personal-ai
ASTRBOT_ROOT=${DEPLOY_ROOT}/astrbot
NAPCAT_ROOT=${DEPLOY_ROOT}/napcat
umask 077

mapfile -t ONEBOT_CONFIGS < <(find "${NAPCAT_ROOT}/config" -maxdepth 1 -type f -name 'onebot11_*.json' -print)
if [[ ${#ONEBOT_CONFIGS[@]} -ne 1 ]]; then
  echo "Expected exactly one logged-in NapCat account." >&2
  exit 1
fi

ACCOUNT_FILE=$(basename "${ONEBOT_CONFIGS[0]}")
ACCOUNT_ID=${ACCOUNT_FILE#onebot11_}
ACCOUNT_ID=${ACCOUNT_ID%.json}
if [[ ! ${ACCOUNT_ID} =~ ^[0-9]+$ ]]; then
  echo "NapCat account configuration name is invalid." >&2
  exit 1
fi
printf 'ACCOUNT=%s\n' "${ACCOUNT_ID}" >"${NAPCAT_ROOT}/secrets/napcat.env"
chmod 600 "${NAPCAT_ROOT}/secrets/napcat.env"

python3 "${DEPLOY_ROOT}/deployment/configure_astrbot_onebot.py" \
  --config "${ASTRBOT_ROOT}/data/cmd_config.json" \
  --token-file "${NAPCAT_ROOT}/secrets/onebot.token" \
  --backup-dir "${ASTRBOT_ROOT}/backups"
python3 "${DEPLOY_ROOT}/deployment/configure_napcat_onebot.py" \
  --config-dir "${NAPCAT_ROOT}/config" \
  --token-file "${NAPCAT_ROOT}/secrets/onebot.token" \
  --backup-dir "${NAPCAT_ROOT}/backups"

sudo systemctl restart astrbot.service
docker compose -f "${NAPCAT_ROOT}/compose.yaml" up -d --force-recreate napcat
echo "OneBot reverse WebSocket configuration finalized. Account identifier was not printed."
