/*
 * WebSocket 接続。
 *
 * サーバーからのメッセージは封筒形式:
 *   {"type": "status", ...}          ドライブ状態（変化があったときのみ）
 *   {"type": "images_changed", path} ファイル操作の通知
 *
 * 切断時は自動で再接続する。Pi の再起動後にブラウザを再読み込みせずに
 * 復帰できるようにするため。
 */

const INITIAL_DELAY = 1000;
const MAX_DELAY = 15000;

export class StatusSocket {
  constructor({ onMessage, onStateChange }) {
    this.onMessage = onMessage;
    this.onStateChange = onStateChange;
    this.socket = null;
    this.delay = INITIAL_DELAY;
    this.timer = null;
    this.closed = false;
  }

  connect() {
    this.closed = false;
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${location.host}/ws/status`;

    this.setState("connecting");
    const socket = new WebSocket(url);
    this.socket = socket;

    socket.addEventListener("open", () => {
      this.delay = INITIAL_DELAY;
      this.setState("open");
    });

    socket.addEventListener("message", (event) => {
      try {
        this.onMessage(JSON.parse(event.data));
      } catch {
        // 解釈できないメッセージは無視する（接続を落とすほどではない）
      }
    });

    socket.addEventListener("close", () => {
      this.setState("closed");
      this.scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      socket.close();
    });
  }

  scheduleReconnect() {
    if (this.closed || this.timer) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.connect();
    }, this.delay);
    // 指数バックオフ。Pi が落ちている間に接続を試み続けて負荷をかけない。
    this.delay = Math.min(this.delay * 2, MAX_DELAY);
  }

  setState(state) {
    if (this.onStateChange) this.onStateChange(state);
  }

  close() {
    this.closed = true;
    if (this.timer) clearTimeout(this.timer);
    if (this.socket) this.socket.close();
  }
}
