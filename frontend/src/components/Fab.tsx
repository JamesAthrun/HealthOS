"use client";

/** 右下角的“＋ 记一笔”悬浮按钮，固定在底部导航上方 */
export function Fab({ onClick, label = "记一笔" }: { onClick: () => void; label?: string }) {
  return (
    <button type="button" className="fab" onClick={onClick} aria-label={label}>
      <span aria-hidden="true">＋</span>
      {label}
    </button>
  );
}
