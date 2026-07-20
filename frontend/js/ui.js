/*
 * ダイアログとトーストの表示。
 *
 * 削除・再起動・シャットダウンは必ず確認を取る。
 */

const toastContainer = () => document.getElementById("toasts");

export function toast(message, level = "info", timeout = 6000) {
  const template = document.getElementById("tpl-toast");
  const fragment = template.content.cloneNode(true);
  const element = fragment.querySelector(".toast");

  element.dataset.level = level;
  element.querySelector(".toast__message").textContent = message;
  element.querySelector(".toast__close").addEventListener("click", () => element.remove());

  toastContainer().append(element);

  if (timeout > 0) {
    setTimeout(() => element.remove(), timeout);
  }
}

function openDialog(dialog) {
  return new Promise((resolve) => {
    const handler = () => {
      dialog.removeEventListener("close", handler);
      resolve(dialog.returnValue === "ok");
    };
    dialog.addEventListener("close", handler);
    dialog.showModal();
  });
}

/** 名前を入力させる。キャンセルなら null を返す。 */
export async function promptName({ title, label = "名前", value = "", note = "", okLabel = "OK" }) {
  const dialog = document.getElementById("dialog-prompt");
  document.getElementById("prompt-title").textContent = title;
  document.getElementById("prompt-label").textContent = label;
  document.getElementById("prompt-ok").textContent = okLabel;

  const noteElement = document.getElementById("prompt-note");
  noteElement.textContent = note;
  noteElement.hidden = !note;

  const input = document.getElementById("prompt-input");
  input.value = value;

  const accepted = await openDialog(dialog);
  const result = input.value.trim();
  return accepted && result ? result : null;
}

/**
 * 破壊的な操作の確認。
 * 削除では件数を明示し、シャットダウンでは影響を明示する。
 */
export async function confirmAction({ title, message, note = "", okLabel = "実行" }) {
  const dialog = document.getElementById("dialog-confirm");
  document.getElementById("confirm-title").textContent = title;
  document.getElementById("confirm-message").textContent = message;
  document.getElementById("confirm-ok").textContent = okLabel;

  const noteElement = document.getElementById("confirm-note");
  noteElement.textContent = note;
  noteElement.hidden = !note;

  return openDialog(dialog);
}

/** 新規ディスクイメージの作成ダイアログ。 */
export async function promptCreateImage() {
  const dialog = document.getElementById("dialog-create");
  const name = document.getElementById("create-name");
  const type = document.getElementById("create-type");
  const diskName = document.getElementById("create-diskname");
  const protect = document.getElementById("create-protect");
  const format = document.getElementById("create-format");

  name.value = "";
  diskName.value = "";
  type.value = "2HD";
  protect.checked = false;
  format.value = "encode";

  const accepted = await openDialog(dialog);
  if (!accepted || !name.value.trim()) return null;

  return {
    name: name.value.trim(),
    disk_type: type.value,
    disk_name: diskName.value.trim() || null,
    write_protected: protect.checked,
    data_format: format.value,
  };
}

/** ディスク属性（FDX ファイル自体の属性）の編集ダイアログ。 */
export async function promptAttributes(current) {
  const dialog = document.getElementById("dialog-attrs");
  const diskName = document.getElementById("attrs-diskname");
  const protect = document.getElementById("attrs-protect");

  diskName.value = current?.name ?? "";
  protect.checked = Boolean(current?.write_protected);

  const accepted = await openDialog(dialog);
  if (!accepted) return null;

  return {
    disk_name: diskName.value.trim() || null,
    write_protected: protect.checked,
  };
}

/** 変換オプションのダイアログ。 */
export async function promptConvert(paths) {
  const dialog = document.getElementById("dialog-convert");
  const target = document.getElementById("convert-target");
  const diskNo = document.getElementById("convert-diskno");
  const diskNoRow = document.getElementById("convert-diskno-row");
  const format = document.getElementById("convert-format");
  const analyze = document.getElementById("convert-analyze");

  target.textContent =
    paths.length === 1
      ? `${paths[0]} を FDX に変換します。`
      : `${paths.length} 件を FDX に変換します。`;

  // ディスク番号が意味を持つのは D88 系のマルチイメージだけ
  const isMulti = paths.some((p) => /\.(d88|d68|d77)$/i.test(p));
  diskNoRow.hidden = !isMulti;

  diskNo.value = "1";
  format.value = "encode";
  analyze.value = "upd765";

  const accepted = await openDialog(dialog);
  if (!accepted) return null;

  return {
    disk_no: Number(diskNo.value) || 1,
    data_format: format.value,
    analyze: analyze.value,
  };
}

/** ディスク情報の表示。パースできなかった場合は生の出力を出す。 */
export async function showDiskInfo(info) {
  const dialog = document.getElementById("dialog-info");
  const body = document.getElementById("info-body");
  body.replaceChildren();

  const rows = [
    ["ディスク名", info.name],
    ["種別", info.disk_type],
    ["回転数", info.rpm ? `${info.rpm} rpm` : null],
    ["シリンダ数", info.cylinders],
    ["ヘッド数", info.heads],
    ["データ形式", info.data_format],
    [
      "ライトプロテクト",
      info.write_protected === null || info.write_protected === undefined
        ? null
        : info.write_protected
          ? "有効"
          : "無効",
    ],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");

  if (rows.length > 0) {
    const table = document.createElement("table");
    table.className = "info-table";
    for (const [label, value] of rows) {
      const tr = document.createElement("tr");
      const th = document.createElement("th");
      th.textContent = label;
      const td = document.createElement("td");
      td.textContent = String(value);
      tr.append(th, td);
      table.append(tr);
    }
    body.append(table);
  }

  // FDX68 のバージョン差で書式が変わっても情報を失わないよう、生の出力も見せる
  if (info.raw_output) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = rows.length > 0 ? "fdxtool の出力" : "fdxtool の出力（解析できませんでした）";
    if (rows.length === 0) details.open = true;
    const pre = document.createElement("pre");
    pre.className = "info-raw";
    pre.textContent = info.raw_output;
    details.append(summary, pre);
    body.append(details);
  }

  await openDialog(dialog);
}
