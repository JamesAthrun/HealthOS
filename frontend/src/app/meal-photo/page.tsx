"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { FoodItemsEditor } from "@/components/FoodItemsEditor";
import { guessMealType, MealTypeChips } from "@/components/forms/MealForm";
import { api, uploadApi } from "@/lib/api";
import { useFoodPreferences } from "@/lib/foodPrefs";
import { type FoodItemInput, type Meal, localInputToIso, toDateTimeLocal } from "@/lib/health";
import { type DraftItem, NutritionCard, toFoodItem } from "@/lib/nutrition";
import { useToast } from "@/lib/toast";
import { useAction } from "@/lib/useAction";
import { useMe } from "@/lib/useMe";

type Consent = { granted: boolean; granted_at: string | null };
type Photo = { id: string };
type Analysis = {
  id: string;
  photo_id: string;
  status: string;
  result: {
    meal_type: Meal["meal_type"];
    food_items: (FoodItemInput & { confidence: number })[];
    overall_confidence: number;
    warnings: string[];
  } | null;
};

const ACCEPT = "image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif";

export default function MealPhotoPage() {
  const me = useMe();
  const toast = useToast();
  const foodPrefs = useFoodPreferences(Boolean(me));
  const { busy, error, setError, run } = useAction();
  const [consent, setConsent] = useState<Consent | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [mealType, setMealType] = useState<Meal["meal_type"]>(() => guessMealType());
  const [eatenAt, setEatenAt] = useState(() => toDateTimeLocal(new Date()));
  const [items, setItems] = useState<DraftItem[]>([]);
  const [notes, setNotes] = useState("");
  const [hint, setHint] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    if (!me) return;
    api<Consent>("/ai-consent").then(setConsent).catch(() => setError("AI 同意状态加载失败"));
  }, [me, setError]);

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

  function selectFile(next: File | null) {
    if (preview) URL.revokeObjectURL(preview);
    setFile(next);
    setPreview(next ? URL.createObjectURL(next) : "");
    setPhoto(null);
    setAnalysis(null);
    setItems([]);
    setHint("");
    setNotes("");
    setConfirmed(false);
    setError("");
    setEatenAt(toDateTimeLocal(new Date()));
  }

  function applyDraft(draft: Analysis) {
    if (!draft.result) throw new Error("识别结果为空");
    setAnalysis(draft);
    setMealType(draft.result.meal_type);
    setItems(draft.result.food_items.map((item) => ({
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
    })));
  }

  async function grantConsent() {
    await run(async () => setConsent(await api<Consent>("/ai-consent", { method: "PUT" })));
  }

  async function analyze() {
    if (!file) return;
    await run(async () => {
      const uploaded = photo ?? await uploadApi<Photo>("/meal-photos", file);
      setPhoto(uploaded);
      applyDraft(await api<Analysis>(`/meal-photos/${uploaded.id}/analyze`, { method: "POST" }));
    }, "识别失败，可稍后重试或手动记录");
  }

  async function reanalyze() {
    if (!photo || !hint.trim()) return;
    const ok = await run(async () => {
      applyDraft(await api<Analysis>(`/meal-photos/${photo.id}/analyze`, { method: "POST", body: { hint: hint.trim() } }));
    }, "重新识别失败，可直接修改下方内容");
    if (ok) {
      setHint("");
      toast("已按你的说明重新识别");
    }
  }

  async function confirm(e: FormEvent) {
    e.preventDefault();
    if (!photo) return;
    const ok = await run(() => api(`/meal-photos/${photo.id}/confirm`, {
      method: "POST",
      body: { eaten_at: localInputToIso(eatenAt), meal_type: mealType, notes: notes || null, food_items: items.map(toFoodItem) },
    }), "保存失败，请检查内容后重试");
    if (ok) {
      setConfirmed(true);
      toast("已计入今天的记录");
    }
  }

  if (!me) return <p className="muted">加载中…</p>;

  if (confirmed) {
    return (
      <section className="card stack" style={{ textAlign: "center" }}>
        <p className="big-number">✅</p>
        <h1>已记录</h1>
        <p className="muted">{items.map((item) => item.name).join("、")}</p>
        <button type="button" onClick={() => selectFile(null)}>再拍一张</button>
        <Link className="button secondary" href="/log/">查看今天的记录</Link>
      </section>
    );
  }

  return (
    <div className="stack">
      <div className="page-head">
        <h1>拍照记饮食</h1>
        <Link className="button secondary" href="/meals/">✍️ 手动</Link>
      </div>
      {error && <p className="error" role="alert">{error}</p>}

      {consent && !consent.granted && (
        <section className="card consent-box stack">
          <p>照片会发送给 DeepSeek 识别，可能包含餐桌环境。只有你点“识别”时才会发送，之后可在“我的 → 账号设置”撤回。</p>
          <button type="button" disabled={busy} onClick={() => void grantConsent()}>同意并继续</button>
        </section>
      )}

      {!analysis && (
        <section className="card stack">
          {preview ? (
            <>
              <div className="photo-preview" role="img" aria-label="待识别的餐食照片" style={{ backgroundImage: `url(${preview})` }} />
              <button type="button" onClick={() => void analyze()} disabled={busy || !consent?.granted}>
                {busy ? "识别中…（约 10–30 秒）" : "识别这张照片"}
              </button>
              <button type="button" className="secondary" disabled={busy} onClick={() => selectFile(null)}>换一张</button>
            </>
          ) : (
            <>
              <div className="add-grid">
                <label className="file-tile">
                  <span>📷</span>拍照
                  <input type="file" accept={ACCEPT} capture="environment" hidden onChange={(e) => selectFile(e.target.files?.[0] ?? null)} />
                </label>
                <label className="file-tile">
                  <span>🖼️</span>从相册选
                  <input type="file" accept={ACCEPT} hidden onChange={(e) => selectFile(e.target.files?.[0] ?? null)} />
                </label>
              </div>
              <p className="muted">支持 JPEG、PNG、WebP、HEIC，最大 10 MB。识别结果只是估算，确认前可以修改。</p>
            </>
          )}
        </section>
      )}

      {analysis?.result && (
        <form className="card stack" onSubmit={confirm}>
          {preview && <div className="photo-preview" role="img" aria-label="餐食照片" style={{ backgroundImage: `url(${preview})` }} />}
          <NutritionCard items={items} />
          <p className="muted">识别把握：{Math.round(analysis.result.overall_confidence * 100)}%</p>
          {analysis.result.warnings.length > 0 && (
            <ul className="warning-list">{analysis.result.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
          )}
          <details className="more consent-box">
            <summary>识别不准？告诉 AI 哪里不对</summary>
            <label>
              说明
              <textarea maxLength={200} value={hint} placeholder="例如：这是一碗牛肉面，不是米饭；只吃了一半" onChange={(e) => setHint(e.target.value)} />
            </label>
            <button type="button" className="secondary" disabled={busy || !hint.trim()} onClick={() => void reanalyze()}>
              {busy ? "识别中…" : "按说明重新识别"}
            </button>
            <p className="muted">会覆盖下方已修改的内容。</p>
          </details>
          <MealTypeChips value={mealType} onChange={setMealType} />
          <label>时间<input type="datetime-local" required value={eatenAt} onChange={(e) => setEatenAt(e.target.value)} /></label>
          <FoodItemsEditor items={items} onChange={setItems} prefs={foodPrefs} />
          <details className="more" open={Boolean(notes)}>
            <summary>备注（可选）</summary>
            <label>备注<textarea maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
          </details>
          <button type="submit" disabled={busy || items.length === 0}>{busy ? "保存中…" : "确认并记录"}</button>
          <button type="button" className="secondary" disabled={busy} onClick={() => selectFile(null)}>放弃，重新拍</button>
        </form>
      )}
    </div>
  );
}
