#!/usr/bin/env bash
#
# Unit Test → Integration Test → ruff → shellcheck の順に実行する。
# いずれかが失敗した時点で非ゼロで終了し、deploy.sh はデプロイを中止する。

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${APP_DIR}"

if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'
    C_GREEN=$'\033[32m'; C_BLUE=$'\033[34m'; C_YELLOW=$'\033[33m'
else
    C_RESET=""; C_BOLD=""; C_GREEN=""; C_BLUE=""; C_YELLOW=""
fi

step() { printf '%s==>%s %s\n' "${C_BLUE}${C_BOLD}" "${C_RESET}" "$*"; }
ok()   { printf '%s  ✓%s %s\n' "${C_GREEN}" "${C_RESET}" "$*"; }
warn() { printf '%s  !%s %s\n' "${C_YELLOW}" "${C_RESET}" "$*" >&2; }

VENV="${APP_DIR}/.venv"
if [ ! -x "${VENV}/bin/python" ]; then
    echo "仮想環境が見つかりません。以下を実行してください:" >&2
    echo "  python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
    exit 1
fi

# 実機のコマンドを絶対に呼ばないよう、テストは必ず mock で動かす
export FDX68_BACKEND=mock

step "Unit Test"
"${VENV}/bin/python" -m pytest tests/unit -q
ok "Unit Test に成功しました"

step "Integration Test"
"${VENV}/bin/python" -m pytest tests/integration -q
ok "Integration Test に成功しました"

step "静的解析（ruff）"
"${VENV}/bin/ruff" check .
ok "lint に成功しました"

step "フォーマット確認（ruff format）"
"${VENV}/bin/ruff" format --check .
ok "フォーマットは適切です"

step "シェルスクリプトの静的解析（shellcheck）"
if command -v shellcheck >/dev/null 2>&1; then
    shellcheck scripts/*.sh
    ok "shellcheck に成功しました"
else
    # 導入されていない環境でもテスト全体を失敗させない（CI では必ず実行される）
    warn "shellcheck が見つかりません（brew install shellcheck で導入できます）"
fi

printf '\n%s%sすべてのテストに成功しました。%s\n' "${C_GREEN}" "${C_BOLD}" "${C_RESET}"
