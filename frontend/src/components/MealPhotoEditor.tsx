"use client";

import { useState } from "react";

import { api, ApiError, uploadApi } from "@/lib/api";
import type { Recognition } from "@/lib/nutrition";

export const PHOTO_ACCEPT = "image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif";
export const MAX_MEAL_PHOTOS = 4;

/**
 * 编辑已有一餐的照片：查看、移除、补拍/从相册添加，并可以用当前照片让 AI 重新识别。
 * 照片选中后立即上传；保存这一餐时才真正更新它的照片列表。
 */
export function MealPhotoEditor({
  photoIds,
  onChange,
  onRecognized,
  disabled,
}: {
  photoIds: string[];
  onChange: (ids: string[]) => void;
  onRecognized: (result: Recognition) => void;
  disabled?: boolean;
}) {
  const [uploading, setUploading] = useState(false);
  const [recognizing, setRecognizing] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const busy = disabled || uploading || recognizing;

  async function addFiles(list: FileList | null) {
    if (!list || list.length === 0) return;
    const room = MAX_MEAL_PHOTOS - photoIds.length;
    const files = Array.from(list).slice(0, room);
    setError(list.length > room ? `最多 ${MAX_MEAL_PHOTOS} 张照片` : "");
    setUploading(true);
    try {
      const ids = [...photoIds];
      for (const file of files) {
        const { id } = await uploadApi<{ id: string }>("/meal-photos", file);
        if (!ids.includes(id)) ids.push(id);
      }
      onChange(ids);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "照片上传失败，请稍后再试");
    } finally {
      setUploading(false);
    }
  }

  async function recognize() {
    setError("");
    setRecognizing(true);
    try {
      const result = await api<Recognition>("/meal-recognitions/preview", {
        method: "POST",
        timeoutMs: 120_000,
        body: { photo_ids: photoIds, note: note.trim() || null },
      });
      onRecognized(result);
      setNote("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "识别失败，请稍后重试");
    } finally {
      setRecognizing(false);
    }
  }

  return (
    <details className="more" open={photoIds.length > 0}>
      <summary>照片{photoIds.length ? `（${photoIds.length} 张）` : ""}</summary>
      <div className="stack">
        {error && <p className="error" role="alert">{error}</p>}
        {photoIds.length > 0 && (
          <div className="photo-strip">
            {photoIds.map((id, index) => (
              <div key={id} className="photo-thumb" style={{ backgroundImage: `url(/api/meal-photos/${id})` }}>
                <a href={`/api/meal-photos/${id}`} target="_blank" rel="noreferrer" aria-label={`查看第 ${index + 1} 张照片`} />
                {!busy && (
                  <button
                    type="button"
                    aria-label={`移除第 ${index + 1} 张`}
                    onClick={() => onChange(photoIds.filter((p) => p !== id))}
                  >✕</button>
                )}
              </div>
            ))}
          </div>
        )}
        {photoIds.length < MAX_MEAL_PHOTOS && (
          <div className="add-grid">
            <label className="file-tile">
              <span>📷</span>{uploading ? "上传中…" : "拍照"}
              <input type="file" accept={PHOTO_ACCEPT} capture="environment" hidden disabled={busy} onChange={(e) => { void addFiles(e.target.files); e.target.value = ""; }} />
            </label>
            <label className="file-tile">
              <span>🖼️</span>{uploading ? "上传中…" : "从相册选"}
              <input type="file" accept={PHOTO_ACCEPT} multiple hidden disabled={busy} onChange={(e) => { void addFiles(e.target.files); e.target.value = ""; }} />
            </label>
          </div>
        )}
        {photoIds.length > 0 && (
          <>
            <label>
              给 AI 的说明（可选）
              <textarea maxLength={300} value={note} placeholder="例如：只吃了一半；还喝了一杯豆浆" onChange={(e) => setNote(e.target.value)} />
            </label>
            <button type="button" className="secondary" disabled={busy} onClick={() => void recognize()}>
              {recognizing ? `识别中…（约 ${photoIds.length > 1 ? "20–40" : "10–30"} 秒）` : "用这些照片重新识别"}
            </button>
            <p className="muted">重新识别会替换下面的食物清单，点“保存”后才生效。移除的照片不会删除，只是不再属于这一餐。</p>
          </>
        )}
      </div>
    </details>
  );
}
