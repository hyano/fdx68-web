#!/usr/bin/env bash
#
# macOS から Raspberry Pi へデプロイする（開発用）。
#
# Pi に git が入っていないこと、そして編集のたびにコミットしたくないことから
# rsync を使う。第三者向けの導入経路は install.sh が担う。
#
# 接続先は .env.deploy から読む（git 管理外）。
# 公開リポジトリに自宅の接続情報を残さないため、ここにハードコードしないこと。

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${APP_DIR}"

if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'
    C_GREEN=$'\033[32m'; C_BLUE=$'\033[34m'; C_RED=$'\033[31m'
else
    C_RESET=""; C_BOLD=""; C_GREEN=""; C_BLUE=""; C_RED=""
fi

step() { printf '%s==>%s %s\n' "${C_BLUE}${C_BOLD}" "${C_RESET}" "$*"; }
ok()   { printf '%s  ✓%s %s\n' "${C_GREEN}" "${C_RESET}" "$*"; }
fail() { printf '%s  ✗%s %s\n' "${C_RED}" "${C_RESET}" "$*" >&2; exit 1; }

SKIP_TESTS=false
[ "${1:-}" = "--skip-tests" ] && SKIP_TESTS=true

# --- 接続先の設定 -----------------------------------------------------------

if [ ! -f "${APP_DIR}/.env.deploy" ]; then
    fail ".env.deploy が見つかりません。
.env.deploy.example をコピーして、接続先を記入してください:
  cp .env.deploy.example .env.deploy"
fi

# shellcheck disable=SC1091
. "${APP_DIR}/.env.deploy"

: "${DEPLOY_HOST:?.env.deploy に DEPLOY_HOST を設定してください}"
: "${DEPLOY_DIR:?.env.deploy に DEPLOY_DIR を設定してください}"

# --- 1. テスト --------------------------------------------------------------

if [ "${SKIP_TESTS}" = true ]; then
    step "テストをスキップします（--skip-tests）"
else
    step "テストを実行しています"
    "${APP_DIR}/scripts/test.sh" || fail "テストに失敗したため、デプロイを中止しました。"
fi

# --- 2. 転送 ----------------------------------------------------------------

step "${DEPLOY_HOST}:${DEPLOY_DIR} へ転送しています"

# --delete の対象はデプロイ先ディレクトリのみ。
# イメージディレクトリは別の場所にあるため、ディスクイメージが消える心配はない。
rsync -az --delete \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '.git/' \
    --exclude '.pytest_cache/' \
    --exclude '.ruff_cache/' \
    --exclude '.env' \
    --exclude '.env.deploy' \
    --exclude '*.log' \
    --exclude 'testdata/images/' \
    "${APP_DIR}/" "${DEPLOY_HOST}:${DEPLOY_DIR}/" \
    || fail "転送に失敗しました。SSH の公開鍵が設定されているか確認してください。"

ok "転送しました"

# --- 3. 依存パッケージの更新 ------------------------------------------------

step "依存パッケージを更新しています"

# shellcheck disable=SC2029  DEPLOY_DIR はローカルで展開したい
ssh "${DEPLOY_HOST}" "
set -e
cd '${DEPLOY_DIR}'
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e .
" || fail "依存パッケージの更新に失敗しました。"

ok "更新しました"

# --- 4. サービスの再起動 ----------------------------------------------------

step "サービスを再起動しています"

ssh "${DEPLOY_HOST}" "sudo systemctl restart fdx68-web" \
    || fail "サービスの再起動に失敗しました。初回は install.sh を実行してください。"

ok "再起動しました"

# --- 5. 疎通確認 ------------------------------------------------------------

if [ -n "${HEALTH_URL:-}" ]; then
    step "疎通を確認しています"

    for _ in $(seq 1 15); do
        if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
            ok "$(curl -fsS "${HEALTH_URL}")"
            printf '\n%s%sデプロイが完了しました。%s\n' "${C_GREEN}" "${C_BOLD}" "${C_RESET}"
            exit 0
        fi
        sleep 1
    done

    fail "疎通を確認できませんでした。./scripts/logs.sh でログを確認してください。"
fi

printf '\n%s%sデプロイが完了しました。%s\n' "${C_GREEN}" "${C_BOLD}" "${C_RESET}"
