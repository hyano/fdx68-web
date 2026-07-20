/*
 * 種別 → アイコンの対応表。
 *
 * 描画側は必ずこの表を経由すること。
 * 将来 SVG スプライトに差し替えるときは、このファイルだけを変更すれば
 * 全画面のアイコンが入れ替わる。
 *
 * fdx と convertible_image が同じアイコンなのは意図的である。
 * どちらもフロッピーディスクイメージであり、違いは「そのまま使えるか」という
 * 状態なので、[要変換] バッジ（CSS が data-kind から生成）で表現している。
 *
 * directory だけ開閉で 2 種類ある。ツリーは深く積み重なるので、
 * 行のインデントだけでなくアイコン自体でも開いているかが分かるようにしている。
 *
 * 5.25 インチのフロッピーを描いた SVG に差し替える際の方針は
 * docs/ui-guidelines.md を参照。
 */

export const ICONS = {
  directory: "📁",
  directory_open: "📂",
  fdx: "💾",
  convertible_image: "💾",
  unsupported: "📄",
};

export function iconFor(kind, { expanded = false } = {}) {
  if (kind === "directory" && expanded) return ICONS.directory_open;
  return ICONS[kind] ?? ICONS.unsupported;
}
