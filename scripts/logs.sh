#!/usr/bin/env bash
#
# Raspberry Pi の状態とログをまとめて取得する。
#
#   ./scripts/logs.sh          直近のログと状態を表示
#   ./scripts/logs.sh -f       ログを追従表示する

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_BLUE=$'\033[34m'; C_RED=$'\033[31m'
else
    C_RESET=""; C_BOLD=""; C_BLUE=""; C_RED=""
fi

section() { printf '\n%s=== %s ===%s\n' "${C_BLUE}${C_BOLD}" "$*" "${C_RESET}"; }
fail()    { printf '%s%s%s\n' "${C_RED}" "$*" "${C_RESET}" >&2; exit 1; }

if [ ! -f "${APP_DIR}/.env.deploy" ]; then
    fail ".env.deploy が見つかりません。.env.deploy.example をコピーして設定してください。"
fi

# shellcheck disable=SC1091
. "${APP_DIR}/.env.deploy"
: "${DEPLOY_HOST:?.env.deploy に DEPLOY_HOST を設定してください}"

LINES="${LINES_TO_SHOW:-200}"

# 追従モード
if [ "${1:-}" = "-f" ] || [ "${1:-}" = "--follow" ]; then
    echo "ログを追従表示します（Ctrl-C で終了）"
    exec ssh -t "${DEPLOY_HOST}" "sudo journalctl -u fdx68-web -f"
fi

section "サービスの状態"
ssh "${DEPLOY_HOST}" "systemctl status fdx68-web --no-pager --lines=0" || true

section "ログ（直近 ${LINES} 行）"
ssh "${DEPLOY_HOST}" "sudo journalctl -u fdx68-web -n ${LINES} --no-pager" || true

section "fddemu プロセス"
# -x で完全一致。部分一致だと fddemu を含む別プロセスを拾ってしまう。
ssh "${DEPLOY_HOST}" "pgrep -ax fddemu || echo '（fddemu は動作していません）'" || true

section "ドライブの状態（fddctl -l）"
# fddctl は root 不要。fddemu 停止中はエラーが出るが、
# これは異常ではないのでそのまま表示する。
ssh "${DEPLOY_HOST}" "fddctl -l 2>&1" || true

section "ディスク使用量"
ssh "${DEPLOY_HOST}" "df -h / | tail -1" || true

section "メモリ"
ssh "${DEPLOY_HOST}" "free -m | head -2" || true

echo
