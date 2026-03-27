#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_CFG="${ROOT_DIR}/config.local.yaml"
SOURCE_CFG="${HOME}/github.com/forchain/UShareIPlay/config.local.yaml"

if [[ ! -f "${TARGET_CFG}" ]]; then
  if [[ -f "${SOURCE_CFG}" ]]; then
    cp "${SOURCE_CFG}" "${TARGET_CFG}"
    echo "已复制 config.local.yaml 到当前项目：${TARGET_CFG}"
  else
    echo "缺少 ${TARGET_CFG}，且未找到源文件：${SOURCE_CFG}" >&2
    exit 1
  fi
fi

mkdir -p logs
uv run ushareiplay