#!/usr/bin/env bash
#
# FDX68 Web Controller のインストーラ。
#
# 環境を検出し、変更内容を提示してから確認を求める「半自動」方式。
# 冪等であり、再実行がそのままアップデート手順になる。
#
#   ./scripts/install.sh              対話的にインストール
#   ./scripts/install.sh --dry-run    実行計画を表示するだけ
#   ./scripts/install.sh --uninstall  サービスと設定を削除
#
# 詳細は docs/guide/installation.md を参照。

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_CONF="${APP_DIR}/packaging/fdx68-source.conf"
SERVICE_NAME="fdx68-web"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SUDOERS_FILE="/etc/sudoers.d/fdx68-web"

# --- オプション -------------------------------------------------------------

DRY_RUN=false
ASSUME_YES=false
UNINSTALL=false
OWN_SHIELD=false
UPGRADE_FDX68=false
SKIP_CHECKSUM=false
FDX68_URL_OVERRIDE="${FDX68_URL_OVERRIDE:-}"
FDX68_SHA256_OVERRIDE="${FDX68_SHA256_OVERRIDE:-}"

# --- 表示 -------------------------------------------------------------------

if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'
else
    C_RESET=""; C_BOLD=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""
fi

info()  { printf '%s\n' "$*"; }
step()  { printf '%s==>%s %s\n' "${C_BLUE}${C_BOLD}" "${C_RESET}" "$*"; }
ok()    { printf '%s  ✓%s %s\n' "${C_GREEN}" "${C_RESET}" "$*"; }
warn()  { printf '%s  !%s %s\n' "${C_YELLOW}" "${C_RESET}" "$*" >&2; }
fail()  { printf '%s  ✗%s %s\n' "${C_RED}" "${C_RESET}" "$*" >&2; exit 1; }

# dry-run では実行せず、実行しようとした内容だけを表示する
run() {
    if [ "${DRY_RUN}" = true ]; then
        printf '     [dry-run] %s\n' "$*"
    else
        "$@"
    fi
}

confirm() {
    local prompt="$1"
    [ "${ASSUME_YES}" = true ] && return 0
    [ "${DRY_RUN}" = true ] && return 0

    local answer
    read -r -p "${prompt} [y/N] " answer </dev/tty
    [[ "${answer}" =~ ^[Yy]$ ]]
}

usage() {
    cat <<'USAGE'
FDX68 Web Controller インストーラ

使い方:
  ./scripts/install.sh [オプション]

オプション:
  --dry-run               実行計画を表示するだけで、何も変更しない
  --yes                   対話的な確認をスキップする（ライセンス同意を除く）
  --uninstall             サービスと設定を削除する
  --i-own-fdx68-shield    FDX68 専用シールドの所有を宣言する（非対話用）
  --upgrade-fdx68         導入済みの FDX68 を更新する
  --fdx68-url URL         FDX68 のダウンロード元を指定する
  --skip-checksum         SHA256 の照合を省略する（非推奨）
  -h, --help              このヘルプを表示する

詳細は docs/guide/installation.md を参照してください。
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=true ;;
        --yes|-y) ASSUME_YES=true ;;
        --uninstall) UNINSTALL=true ;;
        --i-own-fdx68-shield) OWN_SHIELD=true ;;
        --upgrade-fdx68) UPGRADE_FDX68=true ;;
        --skip-checksum) SKIP_CHECKSUM=true ;;
        --fdx68-url) shift; FDX68_URL_OVERRIDE="${1:-}" ;;
        -h|--help) usage; exit 0 ;;
        *) fail "不明なオプション: $1（--help でヘルプを表示）" ;;
    esac
    shift
done

# --- 前提の確認 -------------------------------------------------------------

# root で直接実行させない。必要な箇所だけ内部で sudo を使う。
if [ "$(id -u)" -eq 0 ]; then
    fail "root で直接実行しないでください。一般ユーザーで実行してください（必要な箇所だけ sudo を使います）。"
fi

# sudo を使った時に SUDO_USER が入るので、それを優先して実ユーザーを判定する
INSTALL_USER="${SUDO_USER:-$(id -un)}"
INSTALL_GROUP="$(id -gn "${INSTALL_USER}")"

# getent は Linux にしかないため、無い環境（macOS での dry-run 等）では
# 現在のユーザーの HOME にフォールバックする
if command -v getent >/dev/null 2>&1; then
    INSTALL_HOME="$(getent passwd "${INSTALL_USER}" | cut -d: -f6 || true)"
else
    INSTALL_HOME=""
fi
: "${INSTALL_HOME:=${HOME}}"

# --- アンインストール -------------------------------------------------------

do_uninstall() {
    step "FDX68 Web Controller をアンインストールします"

    if ! confirm "サービスと設定を削除します。よろしいですか？"; then
        info "中止しました。"
        exit 0
    fi

    if systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service"; then
        run sudo systemctl stop "${SERVICE_NAME}" || true
        run sudo systemctl disable "${SERVICE_NAME}" || true
        run sudo rm -f "${SERVICE_FILE}"
        run sudo systemctl daemon-reload
        ok "サービスを削除しました"
    else
        info "  サービスは登録されていません"
    fi

    if [ -f "${SUDOERS_FILE}" ]; then
        run sudo rm -f "${SUDOERS_FILE}"
        ok "sudoers を削除しました"
    fi

    # ディスクイメージは代替不能な資産なので、インストーラが消すことはしない。
    local image_dir
    image_dir="$(grep -E '^FDX68_IMAGE_DIR=' "${APP_DIR}/.env" 2>/dev/null | cut -d= -f2- || true)"

    info ""
    info "以下は${C_BOLD}削除していません${C_RESET}。不要であれば手動で削除してください。"
    info "  ディスクイメージ : ${image_dir:-（.env が見つかりません）}"
    info "  設定ファイル     : ${APP_DIR}/.env"
    info "  FDX68 本体       : /usr/local/bin/fddemu など"
    info "  このリポジトリ   : ${APP_DIR}"
    exit 0
}

[ "${UNINSTALL}" = true ] && do_uninstall

# --- 1. 環境検出 ------------------------------------------------------------

step "環境を確認しています"

OS_CODENAME=""
OS_NAME=""
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_CODENAME="${VERSION_CODENAME:-}"
    OS_NAME="${PRETTY_NAME:-${NAME:-}}"
fi

case "${OS_CODENAME}" in
    bookworm|trixie)
        ok "OS: ${OS_NAME}"
        ;;
    "")
        warn "OS を判別できませんでした。Bookworm / Trixie 以外では動作確認していません。"
        ;;
    *)
        warn "OS: ${OS_NAME}（Bookworm / Trixie 以外では動作確認していません）"
        ;;
esac

ARCH="$(uname -m)"
case "${ARCH}" in
    aarch64|arm64) FDX68_ARCH="aarch64" ;;
    armv7l|armv6l|armhf) FDX68_ARCH="armhf" ;;
    *)
        warn "アーキテクチャ ${ARCH} は FDX68 の対象外です。"
        FDX68_ARCH=""
        ;;
esac
ok "アーキテクチャ: ${ARCH}"

if [ -r /proc/device-tree/model ]; then
    ok "モデル: $(tr -d '\0' < /proc/device-tree/model)"
fi

if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 が見つかりません。sudo apt install -y python3 を実行してください。"
fi

PYTHON_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    fail "Python 3.11 以上が必要です（検出: ${PYTHON_VERSION}）。"
fi
ok "Python: ${PYTHON_VERSION}"

ok "実行ユーザー: ${INSTALL_USER}（グループ: ${INSTALL_GROUP}）"

# --- 2. FDX68 の確認と導入 --------------------------------------------------

BIN_DIR="/usr/local/bin"

find_fdx68() {
    if command -v fddemu >/dev/null 2>&1; then
        dirname "$(command -v fddemu)"
    elif [ -x "${BIN_DIR}/fddemu" ]; then
        echo "${BIN_DIR}"
    else
        echo ""
    fi
}

install_fdx68() {
    [ -z "${FDX68_ARCH}" ] && fail "このアーキテクチャ（${ARCH}）向けの FDX68 は配布されていません。"
    [ -r "${SOURCE_CONF}" ] || fail "配布元の定義が見つかりません: ${SOURCE_CONF}"

    # shellcheck disable=SC1090
    . "${SOURCE_CONF}"

    local url sha256
    if [ -n "${FDX68_URL_OVERRIDE}" ]; then
        url="${FDX68_URL_OVERRIDE}"
        sha256="${FDX68_SHA256_OVERRIDE}"
        warn "ダウンロード元が上書きされています: ${url}"
    else
        eval "url=\${FDX68_URL_${FDX68_ARCH}:-}"
        eval "sha256=\${FDX68_SHA256_${FDX68_ARCH}:-}"
    fi

    [ -n "${url}" ] || fail "${FDX68_ARCH} 向けのダウンロード URL が設定されていません。"

    # ライセンス同意。
    # 配布元の許諾が専用シールド購入者に限られるため、この確認は省略できない。
    # --yes では自動承諾させず、専用フラグを別途要求する。
    if [ "${OWN_SHIELD}" != true ]; then
        info ""
        info "${C_BOLD}FDX68 本体が見つかりませんでした。${C_RESET}"
        info "公式サイトからダウンロードしてインストールできます。"
        info ""
        info "  FDX68 のソフトウェアは、専用シールド(変換基板)を購入された方に限り"
        info "  使用が許諾されています。"
        info ""
        info "  配布元: http://retropc.net/gimons/fdx68/"
        info ""

        if [ "${DRY_RUN}" = true ]; then
            info "     [dry-run] シールド所有の確認をここで行います"
        elif [ -t 0 ] || [ -e /dev/tty ]; then
            local answer
            read -r -p "FDX68 専用シールドをお持ちですか？ [y/N] " answer </dev/tty
            [[ "${answer}" =~ ^[Yy]$ ]] || fail "FDX68 の導入を中止しました。"
        else
            fail "非対話環境では --i-own-fdx68-shield を指定してください。"
        fi
    fi

    step "FDX68 ${FDX68_VERSION:-} を導入します（${FDX68_ARCH}）"
    info "     ${url}"

    if [ "${DRY_RUN}" = true ]; then
        info "     [dry-run] ダウンロード・検証・配置をここで行います"
        return
    fi

    local tmpdir archive
    tmpdir="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '${tmpdir}'" RETURN
    archive="${tmpdir}/fdx68.tar.gz"

    curl -fSL --retry 3 --retry-delay 2 -o "${archive}" "${url}" \
        || fail "ダウンロードに失敗しました: ${url}"
    # stat のオプションは GNU と BSD で異なるため、POSIX の wc -c を使う
    ok "ダウンロードしました（$(wc -c < "${archive}" | tr -d ' ') バイト）"

    # 配布が HTTP（平文）であり、バイナリは root 権限で /dev/mem を触るため、
    # ハッシュ照合は既定で有効にしている。
    if [ "${SKIP_CHECKSUM}" = true ]; then
        warn "SHA256 の照合を省略しました（--skip-checksum）"
    elif [ -z "${sha256}" ]; then
        warn "SHA256 が未設定のため照合できません（packaging/fdx68-source.conf を更新してください）"
        local actual
        actual="$(sha256sum "${archive}" | cut -d' ' -f1)"
        warn "実際の SHA256: ${actual}"
        confirm "照合せずに続行しますか？" || fail "中止しました。"
    else
        local actual
        actual="$(sha256sum "${archive}" | cut -d' ' -f1)"
        if [ "${actual}" != "${sha256}" ]; then
            fail "SHA256 が一致しません。
  期待値: ${sha256}
  実際  : ${actual}
ダウンロードが壊れたか、配布物が更新された可能性があります。
docs/guide/installation.md のトラブルシューティングを参照してください。"
        fi
        ok "SHA256 を照合しました"
    fi

    # tarball はフラット構造（トップレベルディレクトリを持たない）なので
    # 必ず展開先を指定する
    local extract="${tmpdir}/extract"
    mkdir -p "${extract}"
    tar xzf "${archive}" -C "${extract}" || fail "展開に失敗しました。"

    if [ -r "${extract}/VERSION" ]; then
        ok "バージョン: $(cat "${extract}/VERSION")"
    fi

    [ -f "${extract}/fddemu" ] || fail "アーカイブに fddemu が含まれていません。"

    # URL の命名を信用せず、実際のバイナリのアーキテクチャを検証する。
    # 64bit OS に armhf バイナリを置いても /lib/ld-linux-armhf.so.3 がないため
    # そもそも起動しない。配置する前に必ず確認する。
    local file_info
    file_info="$(file -b "${extract}/fddemu" 2>/dev/null || echo "")"
    if [ -n "${file_info}" ]; then
        case "${FDX68_ARCH}:${file_info}" in
            aarch64:*ELF\ 64-bit*aarch64*) ok "アーキテクチャを確認しました（64bit ARM）" ;;
            armhf:*ELF\ 32-bit*ARM*)       ok "アーキテクチャを確認しました（32bit ARM）" ;;
            *)
                fail "ダウンロードした FDX68 のアーキテクチャが一致しません。
  この OS  : ${ARCH}（${FDX68_ARCH} 版が必要）
  バイナリ : ${file_info}
配置せずに中止しました。packaging/fdx68-source.conf の URL を確認してください。"
                ;;
        esac
    else
        warn "file コマンドがないため、バイナリのアーキテクチャを検証できませんでした"
    fi

    for command_name in ${FDX68_COMMANDS}; do
        [ -f "${extract}/${command_name}" ] || continue
        sudo install -o root -g root -m 0755 "${extract}/${command_name}" "${BIN_DIR}/"
    done

    for asset in ${FDX68_ASSETS}; do
        [ -f "${extract}/${asset}" ] || continue
        sudo install -o root -g root -m 0644 "${extract}/${asset}" "${BIN_DIR}/"
    done

    ok "${BIN_DIR} に配置しました"

    "${BIN_DIR}/fddemu" -h >/dev/null 2>&1 \
        || warn "fddemu -h が正常に実行できませんでした。専用シールドの装着を確認してください。"
}

step "FDX68 を確認しています"

FDX68_DIR="$(find_fdx68)"

if [ -z "${FDX68_DIR}" ]; then
    install_fdx68
    FDX68_DIR="${BIN_DIR}"
elif [ "${UPGRADE_FDX68}" = true ]; then
    # エミュレーション中にバイナリを差し替えると実機のディスクアクセスが壊れる
    if pgrep -x fddemu >/dev/null 2>&1; then
        fail "fddemu が動作中です。Web UI から停止してから --upgrade-fdx68 を実行してください。"
    fi
    install_fdx68
else
    # 導入済みの場合は勝手に触らない
    FDX68_VERSION_TEXT="$("${FDX68_DIR}/fddemu" -h 2>&1 | head -1 || echo '不明')"
    ok "導入済み: ${FDX68_VERSION_TEXT}"
    info "     更新する場合は --upgrade-fdx68 を指定してください"
fi

# 必要なコマンドが揃っているか確認する。
# dry-run では実際には導入していないので、この検査は行わない。
if [ "${DRY_RUN}" != true ]; then
    for command_name in fddemu fddctl fdxconv fdxtool; do
        if [ ! -x "${FDX68_DIR}/${command_name}" ] \
            && ! command -v "${command_name}" >/dev/null 2>&1; then
            fail "${command_name} が見つかりません。FDX68 の導入を確認してください。"
        fi
    done
fi

# --- 3. 依存パッケージ ------------------------------------------------------

step "依存パッケージを確認しています"

if python3 -c 'import venv, ensurepip' 2>/dev/null; then
    ok "python3-venv は導入済みです"
else
    info "  python3-venv が必要です"
    if confirm "sudo apt install -y python3-venv を実行しますか？"; then
        run sudo apt-get update
        run sudo apt-get install -y python3-venv
    else
        fail "python3-venv がないと仮想環境を作成できません。"
    fi
fi

# --- 4. 仮想環境 ------------------------------------------------------------

step "仮想環境を準備しています"

if [ ! -d "${APP_DIR}/.venv" ]; then
    run python3 -m venv "${APP_DIR}/.venv"
    ok "仮想環境を作成しました"
else
    ok "仮想環境は作成済みです"
fi

run "${APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip
run "${APP_DIR}/.venv/bin/pip" install --quiet -e "${APP_DIR}"
ok "依存パッケージを導入しました"

# --- 5. イメージディレクトリ ------------------------------------------------

step "ディスクイメージの置き場所を準備しています"

IMAGE_DIR="${INSTALL_HOME}/fdximg"

if [ -d "${IMAGE_DIR}" ]; then
    # 既存のディレクトリの中身には絶対に触れない
    ok "既存のディレクトリを使います: ${IMAGE_DIR}"
else
    run mkdir -p "${IMAGE_DIR}"
    ok "作成しました: ${IMAGE_DIR}"
fi

# --- 6. .env ----------------------------------------------------------------

step "設定ファイルを準備しています"

generate_env() {
    sed \
        -e "s|^FDX68_BACKEND=.*|FDX68_BACKEND=real|" \
        -e "s|^FDX68_IMAGE_DIR=.*|FDX68_IMAGE_DIR=${IMAGE_DIR}|" \
        -e "s|^FDX68_BIN_DIR=.*|FDX68_BIN_DIR=${FDX68_DIR}|" \
        "${APP_DIR}/.env.example"
}

if [ ! -f "${APP_DIR}/.env" ]; then
    if [ "${DRY_RUN}" = true ]; then
        info "     [dry-run] .env を生成します"
    else
        generate_env > "${APP_DIR}/.env"
    fi
    ok ".env を生成しました"
else
    # 既存の設定は上書きしない。差分だけを見せる。
    if [ "${DRY_RUN}" = true ]; then
        info "     [dry-run] 既存の .env は変更しません"
    else
        generate_env > "${APP_DIR}/.env.new"
        if diff -q "${APP_DIR}/.env" "${APP_DIR}/.env.new" >/dev/null 2>&1; then
            rm -f "${APP_DIR}/.env.new"
            ok ".env は最新です"
        else
            warn ".env と既定値に差分があります。必要なら手動で反映してください:"
            diff "${APP_DIR}/.env" "${APP_DIR}/.env.new" | sed 's/^/       /' || true
            info "       差分の内容は ${APP_DIR}/.env.new に保存しました"
        fi
    fi
fi

# 設定から待ち受けアドレスを読む
HOST="$(grep -E '^FDX68_HOST=' "${APP_DIR}/.env" 2>/dev/null | cut -d= -f2- || echo '0.0.0.0')"
PORT="$(grep -E '^FDX68_PORT=' "${APP_DIR}/.env" 2>/dev/null | cut -d= -f2- || echo '8000')"
: "${HOST:=0.0.0.0}"
: "${PORT:=8000}"

# --- 7. sudoers -------------------------------------------------------------

step "sudo の権限を設定しています"

SUDOERS_TMP="$(mktemp)"
sed -e "s|@USER@|${INSTALL_USER}|g" -e "s|@BIN_DIR@|${FDX68_DIR}|g" \
    "${APP_DIR}/packaging/fdx68-web.sudoers.in" > "${SUDOERS_TMP}"

if [ "${DRY_RUN}" = true ]; then
    info "     [dry-run] ${SUDOERS_FILE} に以下を設置します:"
    sed 's/^/       /' "${SUDOERS_TMP}" | grep -v '^\s*#' | grep -v '^\s*$' || true
    rm -f "${SUDOERS_TMP}"
else
    # 構文エラーのある sudoers を置くと sudo 自体が使えなくなるため、
    # 必ず visudo -c で検証してから設置する。
    if sudo visudo -c -f "${SUDOERS_TMP}" >/dev/null 2>&1; then
        sudo install -o root -g root -m 0440 "${SUDOERS_TMP}" "${SUDOERS_FILE}"
        ok "${SUDOERS_FILE} を設置しました"
    else
        rm -f "${SUDOERS_TMP}"
        fail "sudoers の構文検証に失敗しました。設置していません。"
    fi
    rm -f "${SUDOERS_TMP}"
fi

# --- 8. systemd -------------------------------------------------------------

step "systemd サービスを設定しています"

SERVICE_TMP="$(mktemp)"
sed \
    -e "s|@USER@|${INSTALL_USER}|g" \
    -e "s|@GROUP@|${INSTALL_GROUP}|g" \
    -e "s|@APP_DIR@|${APP_DIR}|g" \
    -e "s|@HOST@|${HOST}|g" \
    -e "s|@PORT@|${PORT}|g" \
    "${APP_DIR}/systemd/fdx68-web.service.in" > "${SERVICE_TMP}"

if [ "${DRY_RUN}" = true ]; then
    info "     [dry-run] ${SERVICE_FILE} を設置し、有効化・起動します"
    rm -f "${SERVICE_TMP}"
else
    sudo install -o root -g root -m 0644 "${SERVICE_TMP}" "${SERVICE_FILE}"
    rm -f "${SERVICE_TMP}"
    sudo systemctl daemon-reload
    sudo systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1
    sudo systemctl restart "${SERVICE_NAME}"
    ok "サービスを起動しました"
fi

# --- 9. 疎通確認 ------------------------------------------------------------

if [ "${DRY_RUN}" = true ]; then
    info ""
    ok "dry-run が完了しました。実際には何も変更していません。"
    exit 0
fi

step "起動を確認しています"

CHECK_HOST="${HOST}"
[ "${CHECK_HOST}" = "0.0.0.0" ] && CHECK_HOST="127.0.0.1"

HEALTHY=false
for _ in $(seq 1 20); do
    if curl -fsS "http://${CHECK_HOST}:${PORT}/api/health" >/dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    sleep 1
done

if [ "${HEALTHY}" != true ]; then
    warn "サービスの応答を確認できませんでした。以下でログを確認してください:"
    info "       sudo systemctl status ${SERVICE_NAME}"
    info "       sudo journalctl -u ${SERVICE_NAME} -n 50"
    exit 1
fi

ok "サービスが応答しました"

# --- 完了 -------------------------------------------------------------------

IP_ADDRESS="$(hostname -I 2>/dev/null | awk '{print $1}')"
: "${IP_ADDRESS:=${CHECK_HOST}}"

info ""
info "${C_GREEN}${C_BOLD}インストールが完了しました。${C_RESET}"
info ""
info "  Web UI       : http://${IP_ADDRESS}:${PORT}"
info "  イメージ置き場 : ${IMAGE_DIR}"
info "  設定ファイル   : ${APP_DIR}/.env"
info ""
info "${C_YELLOW}${C_BOLD}【重要】このソフトウェアには認証機能がありません。${C_RESET}"
info "ディスクイメージの削除や Raspberry Pi の再起動・シャットダウンを"
info "誰でも実行できる状態になります。"
info "${C_YELLOW}家庭内 LAN の中だけで使い、インターネットには公開しないでください。${C_RESET}"
info ""
info "  ログの確認   : sudo journalctl -u ${SERVICE_NAME} -f"
info "  サービス再起動 : sudo systemctl restart ${SERVICE_NAME}"
info ""
