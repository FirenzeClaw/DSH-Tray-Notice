#!/usr/bin/env bash
# DSH 托盘启动脚本。
#
# 存在的理由：从 .desktop 或 autostart 启动时，PATH 里通常没有 NVM 的 node
# 目录，python3 也可能不是系统那个。这里把两个环境都补齐再 exec，让托盘脚本
# 本身不必关心自己是怎么被拉起来的。
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(dirname -- "$SCRIPT_DIR")

# NVM 的 node 是 dsh 的运行前提；用用户级安装而不是硬编码某个版本号。
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [ -s "$NVM_DIR/nvm.sh" ]; then
  # shellcheck disable=SC1091
  . "$NVM_DIR/nvm.sh" >/dev/null 2>&1 || true
fi

# 用系统 python3：PyQt6 装在 /usr/lib/python3/dist-packages，虚拟环境里没有。
PYTHON="${DSH_TRAY_PYTHON:-/usr/bin/python3}"
if [ ! -x "$PYTHON" ]; then
  PYTHON=$(command -v python3)
fi

exec "$PYTHON" "$PROJECT_DIR/dsh-tray.py" "$@"
