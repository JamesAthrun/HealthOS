"use client";

import { useEffect, useState } from "react";

import { type MealDraft, MealForm } from "@/components/forms/MealForm";
import type { FormProps } from "@/components/forms/types";
import { api, uploadApi } from "@/lib/api";
import type { FoodItemInput, Meal } from "@/lib/health";
import { useAction } from "@/lib/useAction";

type Consent = { granted: boolean };
type Recognition = {
  meal_type: Meal["meal_type"];
  food_items: (FoodItemInput & { confidence: number })[];
  overall_confidence: number;
  warnings: string[];
};
type Mode = "choose" | "photo" | "text" | "voice" | "manual";

const ACCEPT = "image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif";

function toDraft(result: Recognition, photoId?: string): MealDraft {
  return {
    mealType: result.meal_type,
    photoId,
    confidence: result.overall_confidence,
    warnings: result.warnings,
    items: result.food_items.map((item) => ({
      name: item.name,
      quantity: item.quantity,
      unit: item.unit,
      kcal: item.kcal,
      protein_g: item.protein_g,
      carbs_g: item.carbs_g,
      fat_g: item.fat_g,
      fiber_g: item.fiber_g ?? null,
      sugar_g: item.sugar_g ?? null,
      sodium_mg: item.sodium_mg ?? null,
    })),
  };
}

/** 新建饮食：拍照 / 文字 / 语音（手机输入法的语音转文字）由 AI 生成草稿，或直接填写；最后都进同一个确认表单 */
export function MealCapture({ day, onDone }: Omit<FormProps<Meal>, "initial">) {
  const { busy, error, setError, run } = useAction();
  const [mode, setMode] = useState<Mode>("choose");
  const [consent, setConsent] = useState<Consent | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [photoId, setPhotoId] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [hint, setHint] = useState("");
  const [draft, setDraft] = useState<MealDraft | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    api<Consent>("/ai-consent").then(setConsent).catch(() => setConsent({ granted: false }));
  }, []);

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

  function showDraft(next: MealDraft) {
    setDraft(next);
    setVersion((v) => v + 1);
  }

  function pickFile(next: File | null) {
    if (preview) URL.revokeObjectURL(preview);
    setFile(next);
    setPreview(next ? URL.createObjectURL(next) : "");
    setPhotoId(null);
    setError("");
  }

  async function analyzePhoto(withHint?: string) {
    if (!file) return;
    await run(async () => {
      const id = photoId ?? (await uploadApi<{ id: string }>("/meal-photos", file)).id;
      setPhotoId(id);
      const analysis = await api<{ result: Recognition | null }>(`/meal-photos/${id}/analyze`, {
        method: "POST",
        body: withHint ? { hint: withHint } : undefined,
      });
      if (!analysis.result) throw new Error("识别结果为空");
      showDraft(toDraft(analysis.result, id));
      setHint("");
    }, "识别失败，可稍后重试或直接填写");
  }

  async function analyzeText() {
    await run(async () => {
      showDraft(toDraft(await api<Recognition>("/meal-text/analyze", { method: "POST", body: { text: text.trim() } })));
    }, "识别失败，可稍后重试或直接填写");
  }

  async function grantConsent() {
    await run(async () => setConsent(await api<Consent>("/ai-consent", { method: "PUT" })));
  }

  if (mode === "manual") return <MealForm initial={null} day={day} onDone={onDone} />;

  if (draft) {
    return (
      <div className="stack">
        <button type="button" className="link-button" onClick={() => setDraft(null)}>
          ‹ {mode === "photo" ? "换张照片" : "改一下描述"}
        </button>
        {error && <p className="error" role="alert">{error}</p>}
        {mode === "photo" && (
          <>
            {preview && <div className="photo-preview" role="img" aria-label="餐食照片" style={{ backgroundImage: `url(${preview})` }} />}
            <details className="more consent-box">
              <summary>识别不准？告诉 AI 哪里不对</summary>
              <label>
                说明
                <textarea maxLength={200} value={hint} placeholder="例如：这是牛肉面，不是米饭；只吃了一半" onChange={(e) => setHint(e.target.value)} />
              </label>
              <button type="button" className="secondary" disabled={busy || !hint.trim()} onClick={() => void analyzePhoto(hint.trim())}>
                {busy ? "识别中…" : "按说明重新识别"}
              </button>
            </details>
          </>
        )}
        <MealForm key={version} initial={null} day={day} draft={draft} onDone={onDone} />
      </div>
    );
  }

  if (mode === "choose") {
    return (
      <div className="stack">
        <div className="add-grid three">
          <button type="button" onClick={() => setMode("photo")}><span>📷</span>拍照</button>
          <button type="button" onClick={() => setMode("text")}><span>✍️</span>文字</button>
          <button type="button" onClick={() => setMode("voice")}><span>🎤</span>语音</button>
        </div>
        <p className="muted">AI 会估算食物、份量、热量和营养素，确认前都可以修改。</p>
        <button type="button" className="link-button" onClick={() => setMode("manual")}>不用 AI，直接填写 ›</button>
      </div>
    );
  }

  return (
    <div className="stack">
      <button type="button" className="link-button" onClick={() => { setMode("choose"); setError(""); }}>‹ 换种方式</button>
      {error && <p className="error" role="alert">{error}</p>}
      {consent && !consent.granted && (
        <div className="consent-box stack">
          <p>照片或文字会发送给 DeepSeek 识别。只有你点“识别”时才发送，之后可在“我的 → 账号设置”撤回。</p>
          <button type="button" disabled={busy} onClick={() => void grantConsent()}>同意并继续</button>
        </div>
      )}

      {mode === "photo" && (preview ? (
        <>
          <div className="photo-preview" role="img" aria-label="待识别的餐食照片" style={{ backgroundImage: `url(${preview})` }} />
          <button type="button" disabled={busy || !consent?.granted} onClick={() => void analyzePhoto()}>
            {busy ? "识别中…（约 10–30 秒）" : "识别这张照片"}
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={() => pickFile(null)}>换一张</button>
        </>
      ) : (
        <div className="add-grid">
          <label className="file-tile">
            <span>📷</span>拍照
            <input type="file" accept={ACCEPT} capture="environment" hidden onChange={(e) => pickFile(e.target.files?.[0] ?? null)} />
          </label>
          <label className="file-tile">
            <span>🖼️</span>从相册选
            <input type="file" accept={ACCEPT} hidden onChange={(e) => pickFile(e.target.files?.[0] ?? null)} />
          </label>
        </div>
      ))}

      {(mode === "text" || mode === "voice") && (
        <>
          {mode === "voice" && (
            <p className="reference">🎤 点手机键盘上的<strong>话筒</strong>按钮说话（安卓可长按空格），说完点“识别”。</p>
          )}
          <label>
            {mode === "voice" ? "说说吃了什么" : "吃了什么"}
            <textarea
              autoFocus
              maxLength={300}
              value={text}
              placeholder="例如：中午吃了一碗牛肉面，加了一个卤蛋，喝了半瓶可乐"
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <button type="button" disabled={busy || !text.trim() || !consent?.granted} onClick={() => void analyzeText()}>
            {busy ? "识别中…" : "识别"}
          </button>
        </>
      )}
    </div>
  );
}
