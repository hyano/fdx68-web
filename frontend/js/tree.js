/*
 * イメージブラウザのツリー。
 *
 * 方針（docs/ui-guidelines.md 参照）:
 *  - 展開時に遅延読み込みする（全階層を一度に読まない）
 *  - 展開状態は localStorage に保存し、再読み込み後も復帰する
 *  - ファイル操作の後は影響を受けたノードだけを再取得する
 *  - JS は data-* 属性を出すだけで、見た目は CSS が決める
 */

import { api } from "./api.js";
import { iconFor } from "./icons.js";

const STORAGE_KEY = "fdx68-web.expanded";
const ROOT_PATH = "";

/** バイト数を人間が読める表記にする。 */
function formatSize(bytes) {
  if (bytes === null || bytes === undefined) return "";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[index]}`;
}

/**
 * 更新日時を表示用に整形する。
 * サーバーは UTC の ISO8601 で返すので、ブラウザのローカル時刻で表示する。
 * Pi 側のタイムゾーン設定に表示が左右されないようにするため。
 */
function formatTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function parentOf(path) {
  const index = path.lastIndexOf("/");
  return index < 0 ? ROOT_PATH : path.slice(0, index);
}

export class ImageTree {
  constructor(root) {
    this.root = root;
    this.template = document.getElementById("tpl-node");
    this.expanded = this.loadExpanded();
    this.selected = new Set();
    this.onSelectionChange = null;
  }

  // --- 展開状態の保存 -----------------------------------------------------

  loadExpanded() {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
      return new Set(Array.isArray(stored) ? stored : []);
    } catch {
      return new Set();
    }
  }

  saveExpanded() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...this.expanded]));
    } catch {
      // プライベートモード等で保存できなくても機能自体は動く
    }
  }

  // --- 描画 ---------------------------------------------------------------

  /** ルートを読み込む。以前開いていた枝も復元する。 */
  async load() {
    await this.renderInto(this.root, ROOT_PATH);
    await this.restoreExpanded();
  }

  /**
   * 保存されていた展開状態を復元する。
   * 浅い階層から順に開くことで、親が描画されてから子を開ける。
   */
  async restoreExpanded() {
    const paths = [...this.expanded].sort(
      (a, b) => a.split("/").length - b.split("/").length
    );
    for (const path of paths) {
      const node = this.findNode(path);
      if (node) await this.expand(node, { save: false });
    }
  }

  async renderInto(container, path) {
    try {
      await this.renderEntries(container, path);
    } finally {
      // 行が増減すれば Tab の受け口も作り直す必要がある
      this.syncTabStop();
    }
  }

  async renderEntries(container, path) {
    let listing;
    try {
      listing = await api.list(path);
    } catch (error) {
      // 外部で削除された可能性がある。ノードごと消して実態に合わせる。
      if (error.status === 404) {
        this.removeNode(path);
        return;
      }
      throw error;
    }

    container.replaceChildren();

    if (listing.entries.length === 0) {
      const note = document.createElement("li");
      note.className = "empty-note";
      note.textContent = "（空のフォルダです）";
      container.append(note);
      return;
    }

    for (const entry of listing.entries) {
      container.append(this.createNode(entry));
    }
  }

  createNode(entry) {
    const fragment = this.template.content.cloneNode(true);
    const node = fragment.querySelector(".node");

    node.dataset.kind = entry.kind;
    node.dataset.path = entry.path;
    node.dataset.name = entry.name;
    node.dataset.mounted = entry.mounted_on.join(",");
    node.dataset.selected = String(this.selected.has(entry.path));
    node.setAttribute("draggable", "true");

    if (entry.kind === "directory") {
      node.dataset.expanded = "false";
      node.setAttribute("aria-expanded", "false");
    }

    node.querySelector(".node__icon").textContent = iconFor(entry.kind);
    node.querySelector(".node__name").textContent = entry.name;
    node.querySelector(".node__size").textContent = formatSize(entry.size);
    node.querySelector(".node__mtime").textContent = formatTime(entry.mtime);

    const mountedLabel = entry.mounted_on
      .map((id) => `Drive ${id} に挿入中`)
      .join(" / ");
    node.querySelector(".node__mounted").textContent = mountedLabel;

    return node;
  }

  // --- キーボード操作 -----------------------------------------------------

  /**
   * 表示中のノードのうち 1 つだけを Tab の受け口にする（roving tabindex）。
   * 全行が tabindex="0" だと、ツリーを抜けるのに行数ぶん Tab を押すことになる。
   */
  syncTabStop() {
    const visible = this.visibleNodes();
    // 受け口が残っていればそのまま。消えた（折りたたまれた等）なら先頭に戻す。
    this.setTabStop(visible.find((node) => node.tabIndex === 0) ?? visible[0]);
  }

  setTabStop(stop) {
    for (const node of this.root.querySelectorAll(".node")) {
      node.tabIndex = node === stop ? 0 : -1;
    }
  }

  /** 折りたたまれた枝を除いた、画面に出ているノードを上から順に返す。 */
  visibleNodes() {
    return [...this.root.querySelectorAll(".node")].filter(
      (node) => node.offsetParent !== null
    );
  }

  /** 指定したノードへ Tab の受け口を移してフォーカスする。 */
  focusNode(node) {
    this.setTabStop(node);
    node.focus();
  }

  findNode(path) {
    return this.root.querySelector(`.node[data-path="${CSS.escape(path)}"]`);
  }

  removeNode(path) {
    const node = this.findNode(path);
    if (node) node.remove();
    this.expanded.delete(path);
    this.saveExpanded();
    this.syncTabStop();
  }

  // --- 開閉 ---------------------------------------------------------------

  async toggle(node) {
    if (node.dataset.kind !== "directory") return;
    if (node.dataset.expanded === "true") {
      this.collapse(node);
    } else {
      await this.expand(node);
    }
  }

  async expand(node, { save = true } = {}) {
    const path = node.dataset.path;
    const children = node.querySelector(".node__children");

    node.dataset.expanded = "true";
    node.setAttribute("aria-expanded", "true");
    children.hidden = false;

    // 展開のたびに必ず取り直す。
    // 「折りたたんで開き直せば最新になる」という直感どおりの挙動にするため。
    await this.renderInto(children, path);

    if (save) {
      this.expanded.add(path);
      this.saveExpanded();
    }
  }

  collapse(node) {
    const children = node.querySelector(".node__children");
    node.dataset.expanded = "false";
    node.setAttribute("aria-expanded", "false");
    children.hidden = true;
    this.expanded.delete(node.dataset.path);
    this.saveExpanded();
    // 受け口だった子が隠れた場合に備えて付け替える
    this.syncTabStop();
  }

  // --- 更新 ---------------------------------------------------------------

  /**
   * 展開中のノードだけを再取得する。
   * ツリー全体を作り直さないのは、開いていた枝が閉じると
   * 複数枚組ソフトのフォルダを行き来する作業が中断されるため。
   */
  async refresh() {
    const scrollTop = this.root.parentElement?.scrollTop ?? 0;

    await this.renderInto(this.root, ROOT_PATH);
    await this.restoreExpanded();

    if (this.root.parentElement) this.root.parentElement.scrollTop = scrollTop;
  }

  /** 指定したディレクトリのノードだけを再取得する。 */
  async refreshPath(path) {
    const normalized = path === "." ? ROOT_PATH : path;

    if (normalized === ROOT_PATH) {
      await this.refresh();
      return;
    }

    const node = this.findNode(normalized);
    if (!node || node.dataset.expanded !== "true") {
      // 表示されていないディレクトリなら、その親を更新すれば足りる
      const parent = this.findNode(parentOf(normalized));
      if (parent && parent.dataset.expanded === "true") {
        await this.expand(parent, { save: false });
      } else if (!parent) {
        await this.refresh();
      }
      return;
    }

    await this.expand(node, { save: false });
  }

  // --- 挿入中の印 ---------------------------------------------------------

  /**
   * ドライブ状態が変わったときに呼ぶ。
   * ツリーを再描画せず、該当行の data 属性だけを書き換える。
   */
  updateMounted(drives) {
    const byPath = new Map();
    for (const drive of drives) {
      if (!drive.image_relative) continue;
      const list = byPath.get(drive.image_relative) ?? [];
      list.push(drive.id);
      byPath.set(drive.image_relative, list);
    }

    for (const node of this.root.querySelectorAll(".node")) {
      const ids = byPath.get(node.dataset.path) ?? [];
      node.dataset.mounted = ids.join(",");
      const label = node.querySelector(".node__mounted");
      if (label) {
        label.textContent = ids.map((id) => `Drive ${id} に挿入中`).join(" / ");
      }
    }
  }

  // --- 選択 ---------------------------------------------------------------

  toggleSelection(node, { additive = false } = {}) {
    const path = node.dataset.path;

    if (!additive) {
      const wasOnly = this.selected.size === 1 && this.selected.has(path);
      this.clearSelection();
      if (wasOnly) {
        this.notifySelection();
        return;
      }
      this.selected.add(path);
    } else if (this.selected.has(path)) {
      this.selected.delete(path);
    } else {
      this.selected.add(path);
    }

    this.applySelection();
    this.notifySelection();
  }

  clearSelection() {
    this.selected.clear();
    this.applySelection();
    this.notifySelection();
  }

  applySelection() {
    for (const node of this.root.querySelectorAll(".node")) {
      node.dataset.selected = String(this.selected.has(node.dataset.path));
    }
  }

  notifySelection() {
    if (this.onSelectionChange) this.onSelectionChange([...this.selected]);
  }

  selectedPaths() {
    return [...this.selected];
  }

  kindOf(path) {
    const node = this.findNode(path);
    return node ? node.dataset.kind : null;
  }
}

export { formatSize, formatTime, parentOf, ROOT_PATH };
