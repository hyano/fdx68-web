#!/usr/bin/env bash
#
# CI 専用: FDX68 コマンド群のスタブを生成する。
#
# **実機では絶対に使わないこと。** これは FDX68 本体ではなく、
# install.sh を CI で最後まで実行するためだけの偽物です。
# GPIO も FDD 信号も扱わず、それらしい出力を返すだけです。
#
# FDX68 本体は再配布できないため CI に置けません。一方で検証したいのは
# install.sh とパッケージング（systemd unit / sudoers / .env）であって
# FDX68 そのものではないので、スタブで目的を達成できます。
#
#   scripts/ci/make-fdx68-stub.sh <出力ディレクトリ> [--elf-fddemu]
#
#     --elf-fddemu  fddemu をシェルスクリプトではなく本物の ELF バイナリ
#                   （/bin/true のコピー）にする。install.sh がダウンロード物の
#                   アーキテクチャを file(1) で検証する経路を通すために必要。
#
# 生成先は引数で受け取ったディレクトリだけで、システムには何も配置しません。
# /usr/local/bin への配置や tar 化は呼び出し側（ワークフロー）の責任です。

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_CONF="${APP_DIR}/packaging/fdx68-source.conf"

OUT_DIR=""
ELF_FDDEMU=false

while [ $# -gt 0 ]; do
    case "$1" in
        --elf-fddemu) ELF_FDDEMU=true ;;
        -*) echo "不明なオプション: $1" >&2; exit 1 ;;
        *) OUT_DIR="$1" ;;
    esac
    shift
done

[ -n "${OUT_DIR}" ] || { echo "使い方: $0 <出力ディレクトリ> [--elf-fddemu]" >&2; exit 1; }
[ -r "${SOURCE_CONF}" ] || { echo "配布元の定義が見つかりません: ${SOURCE_CONF}" >&2; exit 1; }

# コマンド名とアセット名は実配布物と揃える。
# shellcheck disable=SC1090
. "${SOURCE_CONF}"

mkdir -p "${OUT_DIR}"

# 実配布物は tarball の中に VERSION を持っている（install.sh が表示に使う）
printf '%s\n' "${FDX68_VERSION}" > "${OUT_DIR}/VERSION"

# --- fddctl ------------------------------------------------------------------
#
# -l の出力は実機の書式に合わせる（docs/reference/fdx68-reference.md）。
# app/command/parser.py の parse_device_list がこれを解析できることまで含めて
# CI で検証したいので、それらしい表を返す。
cat > "${OUT_DIR}/fddctl" <<'STUB'
#!/bin/sh
# CI 専用のスタブ。実機の fddctl ではない。
case "$1" in
    -l)
        cat <<'LIST'
----+----+----+-------------------------------------------------
 ID | WP | CL | DISK IMAGE
----+----+----+-------------------------------------------------
  0 | -- | 00 | EMPTY
  1 | -- | 00 | EMPTY
----+----+----+-------------------------------------------------
LIST
        ;;
esac
exit 0
STUB

# --- fddemu ------------------------------------------------------------------
if [ "${ELF_FDDEMU}" = true ]; then
    # install.sh はダウンロードした fddemu のアーキテクチャを file(1) で検証する。
    # シェルスクリプトでは弾かれるため、実行中のアーキテクチャの ELF が必要になる。
    # 中身は問われないので true(1) の実体をそのまま使う。
    # シェル組み込みの true を拾わないよう、パスを直接探す。
    TRUE_BIN=""
    for candidate in /usr/bin/true /bin/true; do
        if [ -x "${candidate}" ]; then
            TRUE_BIN="${candidate}"
            break
        fi
    done
    [ -n "${TRUE_BIN}" ] || { echo "true(1) の実体が見つかりません" >&2; exit 1; }
    cp "${TRUE_BIN}" "${OUT_DIR}/fddemu"
else
    cat > "${OUT_DIR}/fddemu" <<STUB
#!/bin/sh
# CI 専用のスタブ。実機の fddemu ではない。
echo "FDX68 fddemu version ${FDX68_VERSION} (CI stub)"
exit 0
STUB
fi

# --- その他のコマンド --------------------------------------------------------
#
# install.sh が存在を要求するのは fddemu / fddctl / fdxconv / fdxtool だが、
# 実配布物と同じ顔ぶれを置いた方が配置処理の検証になる。
for command_name in ${FDX68_COMMANDS}; do
    case "${command_name}" in
        fddemu|fddctl) continue ;;
    esac
    cat > "${OUT_DIR}/${command_name}" <<STUB
#!/bin/sh
# CI 専用のスタブ。実機の ${command_name} ではない。
exit 0
STUB
done

for asset in ${FDX68_ASSETS}; do
    : > "${OUT_DIR}/${asset}"
done

for command_name in ${FDX68_COMMANDS}; do
    chmod 0755 "${OUT_DIR}/${command_name}"
done

echo "FDX68 スタブを生成しました: ${OUT_DIR}"
