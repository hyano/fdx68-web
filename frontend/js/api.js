/*
 * API 呼び出し。
 *
 * サーバーはエラー時に {"message": "日本語のメッセージ"} を返すので、
 * それをそのまま例外のメッセージにして UI に表示する。
 */

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    let message = `通信に失敗しました（${response.status}）`;
    try {
      const body = await response.json();
      if (body && body.message) message = body.message;
      else if (body && body.detail) message = String(body.detail);
    } catch {
      // JSON でないレスポンスはそのまま既定のメッセージを使う
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return null;
  return response.json();
}

const json = (body) => ({ body: JSON.stringify(body) });

export const api = {
  ApiError,

  health: () => request("/api/health"),
  status: () => request("/api/status"),

  startFddemu: (options = null) =>
    request("/api/fddemu/start", { method: "POST", ...json({ options }) }),
  stopFddemu: () => request("/api/fddemu/stop", { method: "POST" }),

  insert: (driveId, path) =>
    request(`/api/drives/${driveId}/insert`, { method: "POST", ...json({ path }) }),
  eject: (driveId) => request(`/api/drives/${driveId}/eject`, { method: "POST" }),
  setProtect: (driveId, enabled) =>
    request(`/api/drives/${driveId}/protect`, { method: "POST", ...json({ enabled }) }),

  list: (path = "") => request(`/api/images?path=${encodeURIComponent(path)}`),
  info: (path) => request(`/api/images/info?path=${encodeURIComponent(path)}`),
  downloadUrl: (path) => `/api/images/download?path=${encodeURIComponent(path)}`,

  mkdir: (parent, name) =>
    request("/api/images/mkdir", { method: "POST", ...json({ parent, name }) }),

  createImage: (payload) =>
    request("/api/images/create", { method: "POST", ...json(payload) }),

  convert: (payload) =>
    request("/api/images/convert", { method: "POST", ...json(payload) }),

  move: (paths, destDir, copy = false) =>
    request("/api/images/move", {
      method: "POST",
      ...json({ paths, dest_dir: destDir, copy }),
    }),

  duplicate: (path) =>
    request("/api/images/duplicate", { method: "POST", ...json({ path }) }),

  rename: (path, newName) =>
    request("/api/images/rename", { method: "POST", ...json({ path, new_name: newName }) }),

  setAttributes: (payload) =>
    request("/api/images/attributes", { method: "PATCH", ...json(payload) }),

  remove: (paths) =>
    request("/api/images", { method: "DELETE", ...json({ paths }) }),

  reboot: () => request("/api/system/reboot", { method: "POST" }),
  poweroff: () => request("/api/system/poweroff", { method: "POST" }),

  /*
   * アップロードは fetch では進捗が取れないため XMLHttpRequest を使う。
   * 数 MB〜数十 MB を LAN 越しに送るので、進捗表示がないと固まったように見える。
   */
  upload(path, file, onProgress) {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("path", path);
      form.append("files", file, file.name);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/images/upload");

      xhr.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable && onProgress) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      });

      xhr.addEventListener("load", () => {
        let body = null;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          body = null;
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(body);
        } else {
          reject(new ApiError(body?.message ?? `アップロードに失敗しました（${xhr.status}）`, xhr.status));
        }
      });

      xhr.addEventListener("error", () =>
        reject(new ApiError("通信に失敗しました。", 0))
      );
      xhr.addEventListener("abort", () =>
        reject(new ApiError("アップロードが中断されました。", 0))
      );

      xhr.send(form);
    });
  },
};
