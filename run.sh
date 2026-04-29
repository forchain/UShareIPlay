#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_CFG="${ROOT_DIR}/config.local.yaml"
SOURCE_CFG="${HOME}/github.com/forchain/UShareIPlay/config.local.yaml"
TARGET_VENV="${ROOT_DIR}/.venv"

link_main_branch_venv() {
  # 在 git worktree 中查找 main 分支路径，并尝试链接其 .venv
  local current_path="" branch_ref="" main_worktree="" candidate_venv=""
  while IFS= read -r line; do
    case "${line}" in
      worktree\ *)
        current_path="${line#worktree }"
        ;;
      branch\ refs/heads/main)
        branch_ref="refs/heads/main"
        ;;
      "")
        if [[ "${branch_ref}" == "refs/heads/main" ]]; then
          main_worktree="${current_path}"
          break
        fi
        current_path=""
        branch_ref=""
        ;;
    esac
  done < <(git -C "${ROOT_DIR}" worktree list --porcelain 2>/dev/null || true)

  if [[ -z "${main_worktree}" ]]; then
    return 1
  fi

  candidate_venv="${main_worktree}/.venv"
  if [[ ! -d "${candidate_venv}" ]]; then
    return 1
  fi

  ln -s "${candidate_venv}" "${TARGET_VENV}"
  echo "当前目录缺少 .venv，已链接 main 分支虚拟环境：${candidate_venv}"
  return 0
}

if [[ ! -f "${TARGET_CFG}" ]]; then
  if [[ -f "${SOURCE_CFG}" ]]; then
    cp "${SOURCE_CFG}" "${TARGET_CFG}"
    echo "已复制 config.local.yaml 到当前项目：${TARGET_CFG}"
  else
    echo "缺少 ${TARGET_CFG}，且未找到源文件：${SOURCE_CFG}" >&2
    exit 1
  fi
fi

if [[ ! -e "${TARGET_VENV}" ]]; then
  if ! link_main_branch_venv; then
    echo "当前目录未找到 .venv，且无法链接 main 分支虚拟环境，将继续使用 uv run。" >&2
  fi
fi

mkdir -p logs
uv run ushareiplay