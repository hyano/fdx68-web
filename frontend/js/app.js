/*
 * FDX68 Web Controller のフロントエンド本体。
 *
 * 表示は常に古くなりうる前提で作っている（docs/ui-guidelines.md 参照）。
 * イメージディレクトリは Web UI 以外（rsync、SSH、別のタブ）からも変更されるため。
 */

import { api } from "./api.js";
import { ImageTree, parentOf, ROOT_PATH } from "./tree.js";
import { StatusSocket } from "./ws.js";
import {
  confirmAction,
  promptAttributes,
  promptConvert,
  promptCreateImage,
  promptName,
  showDiskInfo,
  toast,
} from "./ui.js";

/** 内部ドラッグに使う MIME タイプ。OS からのファイル投下と区別するために使う。 */
const INTERNAL_MIME = "application/x-fdx68-paths";

/** シリンダ位置が変化してから「アクセス中の可能性あり」と表示し続ける時間（ミリ秒）。 */
const RECENT_ACCESS_WINDOW = 10000;

const elements = {
  emulator: document.getElementById("emulator"),
  emulatorLabel: document.getElementById("emulator-label"),
  emulatorNote: document.getElementById("emulator-note"),
  drives: document.getElementById("drives"),
  tree: document.getElementById("tree"),
  treeContainer: document.getElementById("tree-container"),
  uploads: document.getElementById("uploads"),
  connection: document.getElementById("connection"),
  bulkBar: document.getElementById("bulk-bar"),
  bulkCount: document.getElementById("bulk-count"),
  fileInput: document.getElementById("file-input"),
};

const state = {
  status: null,
  /** ドライブごとの最終シリンダ値と、それが変化した時刻 */
  cylinderSeen: new Map(),
  uploading: false,
};

const tree = new ImageTree(elements.tree, {});

// --- エラー表示 -------------------------------------------------------------

/**
 * 操作の失敗を表示する。
 *
 * 対象が存在しない場合は、外部で削除された可能性が高いので
 * 一覧を実態に合わせて更新する。表示が古い状態での操作は正常系として扱う。
 */
async function handleError(error, contextPath = null) {
  toast(error.message ?? "操作に失敗しました。", "error");

  if (error.status === 404 && contextPath !== null) {
    await refreshPath(parentOf(contextPath));
    toast("一覧を更新しました。", "info", 3000);
  }
}

async function refreshPath(path) {
  try {
    await tree.refreshPath(path);
  } catch (error) {
    toast(error.message ?? "一覧の更新に失敗しました。", "error");
  }
}

// --- ドライブの表示 ---------------------------------------------------------

function renderStatus(status) {
  state.status = status;

  elements.emulator.dataset.running = String(status.fddemu_running);
  elements.emulatorLabel.textContent = status.fddemu_running
    ? "動作中"
    : "停止中";
  elements.emulatorNote.textContent = status.fddemu_running
    ? ""
    : (status.message ?? "起動すると X68000 からドライブが見えるようになります。");

  renderDrives(status.drives);
  tree.updateMounted(status.drives);
}

function renderDrives(drives) {
  const template = document.getElementById("tpl-drive");
  elements.drives.replaceChildren();

  if (drives.length === 0) {
    const note = document.createElement("p");
    note.className = "note";
    note.textContent = "fddemu が停止しているため、ドライブ情報はありません。";
    elements.drives.append(note);
    return;
  }

  for (const drive of drives) {
    const fragment = template.content.cloneNode(true);
    const card = fragment.querySelector(".drive");

    card.dataset.drive = String(drive.id);
    card.dataset.state = drive.inserted ? "inserted" : "empty";
    card.dataset.protected = String(drive.write_protected);
    card.dataset.recent = String(isRecentlyAccessed(drive));

    card.querySelector(".drive__title").textContent = `Drive ${drive.id}`;
    const imagePath = drive.image_relative || drive.image;
    const imageCell = card.querySelector(".drive__image");
    imageCell.textContent = drive.inserted ? imagePath.split("/").pop() : "（未挿入）";
    imageCell.title = drive.inserted ? imagePath : "";
    card.querySelector(".drive__cylinder").textContent =
      drive.cylinder !== null && drive.cylinder !== undefined
        ? String(drive.cylinder)
        : (drive.cylinder_raw ?? "—");

    const ejectButton = card.querySelector(".drive__eject");
    ejectButton.disabled = !drive.inserted;
    ejectButton.addEventListener("click", async () => {
      try {
        renderStatus(await api.eject(drive.id));
        toast(`Drive ${drive.id} をイジェクトしました。`, "success", 3000);
      } catch (error) {
        await handleError(error);
      }
    });

    const protectButton = card.querySelector(".drive__protect");
    protectButton.disabled = !drive.inserted;
    protectButton.textContent = drive.write_protected
      ? "プロテクト解除"
      : "プロテクト設定";
    protectButton.addEventListener("click", async () => {
      try {
        renderStatus(await api.setProtect(drive.id, !drive.write_protected));
      } catch (error) {
        await handleError(error);
      }
    });

    elements.drives.append(card);
  }
}

/**
 * シリンダ位置が最近変化したかを判定する。
 *
 * ヘッドシークの痕跡であり、X68000 がディスクにアクセスした可能性を示す。
 * ハード的な保証ではないヒントとして扱う。
 */
function isRecentlyAccessed(drive) {
  const previous = state.cylinderSeen.get(drive.id);
  const now = Date.now();

  if (!previous || previous.cylinder !== drive.cylinder) {
    state.cylinderSeen.set(drive.id, { cylinder: drive.cylinder, at: now });
    // 初回は「変化」ではないので警告しない
    return Boolean(previous);
  }

  return now - previous.at < RECENT_ACCESS_WINDOW;
}

function anyDriveRecentlyAccessed() {
  return [...state.cylinderSeen.values()].some(
    (entry) => Date.now() - entry.at < RECENT_ACCESS_WINDOW
  );
}

/** アクセス中かもしれないときに一言添える。 */
function accessWarning() {
  return anyDriveRecentlyAccessed()
    ? "X68000 がディスクにアクセス中の可能性があります。"
    : "";
}

// --- fddemu の制御 ----------------------------------------------------------

document.getElementById("btn-start").addEventListener("click", async () => {
  try {
    renderStatus(await api.startFddemu());
    toast("fddemu を起動しました。", "success", 3000);
  } catch (error) {
    await handleError(error);
  }
});

document.getElementById("btn-stop").addEventListener("click", async () => {
  const ok = await confirmAction({
    title: "fddemu を停止しますか？",
    message: "停止すると X68000 からドライブが見えなくなります。",
    note: accessWarning() || "X68000 がディスクにアクセス中でないことを確認してください。",
    okLabel: "停止",
  });
  if (!ok) return;

  try {
    renderStatus(await api.stopFddemu());
    toast("fddemu を停止しました。", "success", 3000);
  } catch (error) {
    await handleError(error);
  }
});

// --- システム操作 -----------------------------------------------------------

document.getElementById("btn-reboot").addEventListener("click", async () => {
  const ok = await confirmAction({
    title: "本当に Raspberry Pi を再起動しますか？",
    message: "再起動中は Web UI にアクセスできなくなります。",
    note: accessWarning() || "X68000 の電源を切ってから実行することを推奨します。",
    okLabel: "再起動",
  });
  if (!ok) return;

  try {
    await api.reboot();
    toast("再起動を開始しました。しばらくお待ちください。", "warning", 0);
  } catch (error) {
    await handleError(error);
  }
});

document.getElementById("btn-poweroff").addEventListener("click", async () => {
  const ok = await confirmAction({
    title: "本当に Raspberry Pi をシャットダウンしますか？",
    message: "シャットダウン後は Web UI にアクセスできなくなります。",
    note: accessWarning() || "再度使うには Raspberry Pi の電源を入れ直す必要があります。",
    okLabel: "シャットダウン",
  });
  if (!ok) return;

  try {
    await api.poweroff();
    toast("シャットダウンを開始しました。", "warning", 0);
  } catch (error) {
    await handleError(error);
  }
});

/**
 * サービスが再起動して別のプロセスとして立ち上がるのを待つ。
 *
 * health の落下を待つ方式にしていないのは、再起動が速いと落下を観測できず
 * 取りこぼすため。プロセス起動時刻 started_at の変化で判定する。
 */
async function waitForRestart(previousStartedAt) {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  // 停止前の古いプロセスが応答してしまうため、少し待ってから見に行く
  await sleep(1000);

  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    try {
      const health = await api.health();
      if (health.started_at !== previousStartedAt) return true;
    } catch {
      // 再起動中は接続できなくて当然なので、黙って次の試行へ進む
    }
    await sleep(500);
  }
  return false;
}

document.getElementById("btn-restart-service").addEventListener("click", async () => {
  const ok = await confirmAction({
    title: "Web UI サービスを再起動しますか？",
    message: "数秒間 Web UI が応答しなくなります。復帰すると自動的に再読み込みされます。",
    note: "fddemu は動作を続けるため、X68000 のドライブは維持されます。",
    okLabel: "再起動",
  });
  if (!ok) return;

  try {
    // 再起動を投げる前に、いまのプロセスの起動時刻を控えておく
    const { started_at: previousStartedAt } = await api.health();
    await api.restartService();
    toast("Web UI を再起動しています…", "warning", 0);

    if (await waitForRestart(previousStartedAt)) {
      location.reload();
    } else {
      toast("再起動を確認できませんでした。手動で再読み込みしてください。", "error", 0);
    }
  } catch (error) {
    await handleError(error);
  }
});

// --- ツリーの操作 -----------------------------------------------------------

/** 選択中のフォルダ（なければルート）を返す。アップロード先の決定に使う。 */
function currentFolder() {
  const selected = tree.selectedPaths();
  for (const path of selected) {
    if (tree.kindOf(path) === "directory") return path;
  }
  return ROOT_PATH;
}

elements.tree.addEventListener("click", async (event) => {
  const node = event.target.closest(".node");
  if (!node) return;

  const path = node.dataset.path;
  const name = node.dataset.name;

  // 開閉
  if (event.target.closest(".node__twisty")) {
    await tree.toggle(node);
    return;
  }

  // 各操作
  const actions = {
    ".node__insert0": () => insertInto(0, path),
    ".node__insert1": () => insertInto(1, path),
    ".node__convert": () => convertPaths([path]),
    ".node__info": () => showInfo(path),
    ".node__attrs": () => editAttributes(path),
    ".node__duplicate": () => duplicate(path),
    ".node__download": () => download(path),
    ".node__rename": () => rename(path, name),
    ".node__delete": () => remove([path]),
  };

  for (const [selector, handler] of Object.entries(actions)) {
    if (event.target.closest(selector)) {
      // メニューを閉じる
      const menu = event.target.closest("details");
      if (menu) menu.open = false;
      await handler();
      return;
    }
  }

  // 行のクリックは選択。ディレクトリはダブルクリックでも開閉する。
  if (event.target.closest(".node__row")) {
    tree.toggleSelection(node, { additive: event.shiftKey || event.metaKey || event.ctrlKey });
  }
});

elements.tree.addEventListener("dblclick", async (event) => {
  const node = event.target.closest(".node");
  if (node && node.dataset.kind === "directory") {
    await tree.toggle(node);
  }
});

// キーボード操作（上下で移動、左右で開閉）
elements.tree.addEventListener("keydown", async (event) => {
  const node = event.target.closest(".node");
  if (!node) return;

  const visible = [...elements.tree.querySelectorAll(".node")].filter(
    (candidate) => candidate.offsetParent !== null
  );
  const index = visible.indexOf(node);

  if (event.key === "ArrowDown" && index < visible.length - 1) {
    event.preventDefault();
    visible[index + 1].focus();
  } else if (event.key === "ArrowUp" && index > 0) {
    event.preventDefault();
    visible[index - 1].focus();
  } else if (event.key === "ArrowRight" && node.dataset.kind === "directory") {
    event.preventDefault();
    if (node.dataset.expanded !== "true") await tree.expand(node);
  } else if (event.key === "ArrowLeft" && node.dataset.kind === "directory") {
    event.preventDefault();
    if (node.dataset.expanded === "true") tree.collapse(node);
  }
});

// --- 個別の操作 -------------------------------------------------------------

async function insertInto(driveId, path) {
  const warning = accessWarning();
  if (warning) {
    const ok = await confirmAction({
      title: "ディスクを交換しますか？",
      message: warning,
      note: "アクセス中に交換すると、X68000 側で読み書きが失敗することがあります。",
      okLabel: "交換する",
    });
    if (!ok) return;
  }

  try {
    renderStatus(await api.insert(driveId, path));
    toast(`Drive ${driveId} に挿入しました。`, "success", 3000);
  } catch (error) {
    await handleError(error, path);
  }
}

async function convertPaths(paths) {
  const options = await promptConvert(paths);
  if (!options) return;

  let succeeded = 0;
  const failures = [];

  // 1 件ずつ順に処理し、途中で失敗しても残りを続ける
  for (const path of paths) {
    try {
      await api.convert({ path, ...options });
      succeeded += 1;
    } catch (error) {
      failures.push(`${path}: ${error.message}`);
    }
  }

  reportBulk("変換", succeeded, failures);
  await refreshPath(parentOf(paths[0]));
  tree.clearSelection();
}

async function showInfo(path) {
  try {
    await showDiskInfo(await api.info(path));
  } catch (error) {
    await handleError(error, path);
  }
}

async function editAttributes(path) {
  let current = null;
  try {
    current = await api.info(path);
  } catch (error) {
    await handleError(error, path);
    return;
  }

  const values = await promptAttributes(current);
  if (!values) return;

  try {
    await api.setAttributes({ path, ...values });
    toast("ディスク属性を変更しました。", "success", 3000);
    await refreshPath(parentOf(path));
  } catch (error) {
    await handleError(error, path);
  }
}

async function duplicate(path) {
  const warning = accessWarning();
  if (warning) {
    const ok = await confirmAction({
      title: "複製しますか？",
      message: warning,
      note: "X68000 が書き込み中のイメージを複製すると、不整合なコピーになることがあります。",
      okLabel: "複製する",
    });
    if (!ok) return;
  }

  try {
    const result = await api.duplicate(path);
    toast(`複製しました: ${result.path}`, "success");
    await refreshPath(parentOf(path));
  } catch (error) {
    await handleError(error, path);
  }
}

function download(path) {
  // ブラウザのダウンロード機能に任せる
  const link = document.createElement("a");
  link.href = api.downloadUrl(path);
  link.download = "";
  link.click();
}

async function rename(path, currentName) {
  const newName = await promptName({
    title: "名前の変更",
    value: currentName,
    note: "拡張子を変更しても形式は変換されません。変換は「FDX に変換」から行ってください。",
    okLabel: "変更",
  });
  if (!newName || newName === currentName) return;

  try {
    await api.rename(path, newName);
    toast("名前を変更しました。", "success", 3000);
    await refreshPath(parentOf(path));
  } catch (error) {
    await handleError(error, path);
  }
}

async function remove(paths) {
  const message =
    paths.length === 1
      ? `「${paths[0].split("/").pop()}」を削除しますか？`
      : `${paths.length} 件のファイル・フォルダを削除しますか？`;

  const ok = await confirmAction({
    title: "削除の確認",
    message,
    note: "この操作は元に戻せません。",
    okLabel: "削除",
  });
  if (!ok) return;

  try {
    const result = await api.remove(paths);
    const failures = result.results
      .filter((entry) => !entry.success)
      .map((entry) => `${entry.path}: ${entry.message}`);
    reportBulk("削除", result.results.length - failures.length, failures);
  } catch (error) {
    await handleError(error);
    return;
  }

  const parents = new Set(paths.map(parentOf));
  for (const parent of parents) await refreshPath(parent);
  tree.clearSelection();
}

/**
 * 一括操作の結果を報告する。
 * 一部が失敗しても残りは処理されているので、成功数と失敗理由の両方を出す。
 */
function reportBulk(label, succeeded, failures) {
  if (succeeded > 0) {
    toast(`${succeeded} 件を${label}しました。`, "success", 4000);
  }
  for (const failure of failures) {
    toast(`${label}できませんでした — ${failure}`, "error", 0);
  }
}

// --- ツールバー -------------------------------------------------------------

document.getElementById("btn-refresh").addEventListener("click", async () => {
  await tree.refresh();
  toast("一覧を更新しました。", "info", 2000);
});

document.getElementById("btn-mkdir").addEventListener("click", async () => {
  const parent = currentFolder();
  const name = await promptName({
    title: "新規フォルダ",
    label: "フォルダ名",
    note: parent ? `作成先: ${parent}` : "作成先: ルート",
    okLabel: "作成",
  });
  if (!name) return;

  try {
    await api.mkdir(parent, name);
    toast("フォルダを作成しました。", "success", 3000);
    await refreshPath(parent);
  } catch (error) {
    await handleError(error);
  }
});

document.getElementById("btn-create").addEventListener("click", async () => {
  const parent = currentFolder();
  const values = await promptCreateImage();
  if (!values) return;

  try {
    const result = await api.createImage({ parent, ...values });
    toast(
      `${result.path} を作成しました。使用前に X68000 側でフォーマットしてください。`,
      "success",
      8000
    );
    await refreshPath(parent);
  } catch (error) {
    await handleError(error);
  }
});

document.getElementById("btn-upload").addEventListener("click", () => {
  elements.fileInput.click();
});

elements.fileInput.addEventListener("change", async () => {
  const files = [...elements.fileInput.files];
  elements.fileInput.value = "";
  if (files.length > 0) await uploadFiles(currentFolder(), files);
});

// --- 一括操作バー -----------------------------------------------------------

tree.onSelectionChange = (paths) => {
  elements.bulkBar.hidden = paths.length === 0;
  elements.bulkCount.textContent = `${paths.length} 件選択中`;
};

document.getElementById("btn-bulk-delete").addEventListener("click", () => {
  const paths = tree.selectedPaths();
  if (paths.length > 0) remove(paths);
});

document.getElementById("btn-bulk-convert").addEventListener("click", () => {
  const paths = tree
    .selectedPaths()
    .filter((path) => tree.kindOf(path) === "convertible_image");

  if (paths.length === 0) {
    toast("変換できるイメージが選択されていません。", "warning", 4000);
    return;
  }
  convertPaths(paths);
});

document.getElementById("btn-bulk-clear").addEventListener("click", () => {
  tree.clearSelection();
});

// --- ドラッグ＆ドロップ -----------------------------------------------------

/*
 * 外部からのファイル投下（アップロード）と、ツリー内部の移動を区別する。
 * 内部ドラッグには独自の MIME タイプを載せているので、それで判別する。
 * ここを曖昧にすると、OS からのファイル投下を移動と誤認して失敗する。
 */
function isExternalFileDrag(event) {
  return [...(event.dataTransfer?.types ?? [])].includes("Files");
}

elements.tree.addEventListener("dragstart", (event) => {
  const node = event.target.closest(".node");
  if (!node) return;

  // 選択済みの行をドラッグしたら選択分すべてを運ぶ
  const selected = tree.selectedPaths();
  const paths = selected.includes(node.dataset.path) ? selected : [node.dataset.path];

  event.dataTransfer.setData(INTERNAL_MIME, JSON.stringify(paths));
  event.dataTransfer.effectAllowed = "copyMove";
});

function clearDropTargets() {
  for (const node of elements.tree.querySelectorAll('.node[data-droptarget="true"]')) {
    node.dataset.droptarget = "false";
  }
  elements.treeContainer.dataset.dragover = "false";
}

/** 投入先のフォルダを決める。フォルダ以外に落とした場合はその親。 */
function dropTargetFolder(event) {
  const node = event.target.closest(".node");
  if (!node) return { path: ROOT_PATH, node: null };

  if (node.dataset.kind === "directory") {
    return { path: node.dataset.path, node };
  }
  return { path: parentOf(node.dataset.path), node: null };
}

elements.treeContainer.addEventListener("dragover", (event) => {
  event.preventDefault();

  // Option (Alt) 併用でコピー。カーソル表示も切り替える。
  event.dataTransfer.dropEffect =
    !isExternalFileDrag(event) && event.altKey ? "copy" : isExternalFileDrag(event) ? "copy" : "move";

  clearDropTargets();
  elements.treeContainer.dataset.dragover = "true";

  // 投入先のフォルダ行を 1 つだけハイライトする。
  // どこに入るのか分からないまま数 MB を転送させないため。
  const target = dropTargetFolder(event);
  if (target.node) target.node.dataset.droptarget = "true";
});

elements.treeContainer.addEventListener("dragleave", (event) => {
  if (event.target === elements.treeContainer) clearDropTargets();
});

elements.treeContainer.addEventListener("drop", async (event) => {
  event.preventDefault();

  const target = dropTargetFolder(event);
  clearDropTargets();

  if (isExternalFileDrag(event)) {
    const files = [...event.dataTransfer.files];
    if (files.length > 0) await uploadFiles(target.path, files);
    return;
  }

  const raw = event.dataTransfer.getData(INTERNAL_MIME);
  if (!raw) return;

  let paths;
  try {
    paths = JSON.parse(raw);
  } catch {
    return;
  }

  await movePaths(paths, target.path, event.altKey);
});

async function movePaths(paths, destDir, copy) {
  try {
    const result = await api.move(paths, destDir, copy);
    const failures = result.results
      .filter((entry) => !entry.success)
      .map((entry) => `${entry.path}: ${entry.message}`);

    reportBulk(copy ? "コピー" : "移動", result.results.length - failures.length, failures);
  } catch (error) {
    await handleError(error);
    return;
  }

  const parents = new Set(paths.map(parentOf));
  parents.add(destDir);
  for (const parent of parents) await refreshPath(parent);
  tree.clearSelection();
}

// --- アップロード -----------------------------------------------------------

async function uploadFiles(destDir, files) {
  const warning = accessWarning();
  if (warning) {
    toast(
      `${warning} アップロード中の書き込みが影響する場合があります。`,
      "warning",
      6000
    );
  }

  state.uploading = true;
  const template = document.getElementById("tpl-upload");

  // 並行させず 1 つずつ順に送る。Pi の CPU と SD カード I/O を飽和させないため。
  for (const file of files) {
    const fragment = template.content.cloneNode(true);
    const row = fragment.querySelector(".upload");
    const progress = row.querySelector(".upload__progress");
    const status = row.querySelector(".upload__status");

    row.querySelector(".upload__name").textContent = file.name;
    status.textContent = "送信中…";
    elements.uploads.append(row);

    try {
      const result = await api.upload(destDir, file, (percent) => {
        progress.value = percent;
      });

      const entry = result?.results?.[0];
      if (entry && !entry.success) {
        status.textContent = entry.message ?? "失敗";
        toast(`${file.name}: ${entry.message}`, "error", 0);
      } else {
        progress.value = 100;
        status.textContent = "完了";
        setTimeout(() => row.remove(), 4000);
      }
    } catch (error) {
      status.textContent = "失敗";
      toast(`${file.name}: ${error.message}`, "error", 0);
    }
  }

  state.uploading = false;
  await refreshPath(destDir);
}

// --- WebSocket と自動更新 ---------------------------------------------------

const socket = new StatusSocket({
  onMessage: async (message) => {
    if (message.type === "status") {
      renderStatus(message);
    } else if (message.type === "images_changed") {
      // 他のタブや端末からの操作を反映する
      await refreshPath(message.path ?? ROOT_PATH);
    }
  },
  onStateChange: (connectionState) => {
    elements.connection.dataset.state = connectionState;
    const labels = {
      connecting: "接続中…",
      open: "接続済み",
      closed: "切断（再接続します）",
    };
    elements.connection.querySelector(".connection__label").textContent =
      labels[connectionState] ?? connectionState;
  },
});

/*
 * ウィンドウにフォーカスが戻ったら更新する。
 * 「macOS から rsync してブラウザに戻る」という頻発する操作で、
 * 明示的な更新操作を不要にするため。
 */
document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState !== "visible" || state.uploading) return;
  await tree.refresh();
});

// --- 起動 -------------------------------------------------------------------

async function main() {
  try {
    renderStatus(await api.status());
  } catch (error) {
    toast(error.message ?? "状態を取得できませんでした。", "error");
  }

  try {
    await tree.load();
  } catch (error) {
    toast(error.message ?? "イメージ一覧を取得できませんでした。", "error");
  }

  socket.connect();
}

main();
