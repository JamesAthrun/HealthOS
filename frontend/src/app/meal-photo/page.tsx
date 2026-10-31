"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { api, ApiError, uploadApi } from "@/lib/api";
import { type FoodItemInput, localInputToIso, toDateTimeLocal } from "@/lib/health";
import { useMe } from "@/lib/useMe";

type Consent = { granted: boolean; granted_at: string | null };
type Photo = { id: string; width: number; height: number; byte_size: number };
type MealType = "breakfast" | "lunch" | "dinner" | "snack";
type RecognitionItem = FoodItemInput & { confidence: number };
type Analysis = {
  id: string;
  photo_id: string;
  status: string;
  result: {
    meal_type: MealType;
    food_items: RecognitionItem[];
    overall_confidence: number;
    warnings: string[];
  } | null;
};

const EMPTY_ITEM: FoodItemInput = {
  name: "",
  quantity: 1,
  unit: "份",
  kcal: 0,
  protein_g: 0,
  carbs_g: 0,
  fat_g: 0,
};

export default function MealPhotoPage() {
  const me = useMe();
  const [consent, setConsent] = useState<Consent | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [mealType, setMealType] = useState<MealType>("lunch");
  const [eatenAt, setEatenAt] = useState(() => toDateTimeLocal(new Date()));
  const [items, setItems] = useState<FoodItemInput[]>([]);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    if (!me) return;
    api<Consent>("/ai-consent").then(setConsent).catch(() => setError("AI 同意状态加载失败"));
  }, [me]);

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

  if (!me) return <p>加载中…</p>;

  function selectFile(next: File | null) {
    if (preview) URL.revokeObjectURL(preview);
    setFile(next);
    setPreview(next ? URL.createObjectURL(next) : "");
    setPhoto(null);
    setAnalysis(null);
    setItems([]);
    setConfirmed(false);
    setError("");
  }

  async function grantConsent() {
    setError("");
    try {
      setConsent(await api<Consent>("/ai-consent", { method: "PUT" }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "操作失败");
    }
  }

  async function uploadAndAnalyze() {
    if (!file) {
      setError("请先拍照或选择一张餐食照片");
      return;
    }
    if (!consent?.granted) {
      setError("请先阅读并同意 AI 图片处理说明");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const uploaded = photo ?? await uploadApi<Photo>("/meal-photos", file);
      setPhoto(uploaded);
      const draft = await api<Analysis>(`/meal-photos/${uploaded.id}/analyze`, { method: "POST" });
      setAnalysis(draft);
      if (!draft.result) throw new Error("识别结果为空");
      setMealType(draft.result.meal_type);
      setItems(draft.result.food_items.map((item) => ({
        name: item.name,
        quantity: item.quantity,
        unit: item.unit,
        kcal: item.kcal,
        protein_g: item.protein_g,
        carbs_g: item.carbs_g,
        fat_g: item.fat_g,
      })));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "识别失败，可稍后重试或手工记录");
    } finally {
      setBusy(false);
    }
  }

  function updateItem(index: number, field: keyof FoodItemInput, value: string) {
    setItems((current) => current.map((item, itemIndex) => {
      if (itemIndex !== index) return item;
      const numeric = field === "name" || field === "unit" ? value : Number(value);
      return { ...item, [field]: numeric };
    }));
  }

  async function confirm(e: FormEvent) {
    e.preventDefault();
    if (!photo || !analysis) return;
    setBusy(true);
    setError("");
    try {
      await api(`/meal-photos/${photo.id}/confirm`, {
        method: "POST",
        body: {
          eaten_at: localInputToIso(eatenAt),
          meal_type: mealType,
          notes: notes || null,
          food_items: items,
        },
      });
      setConfirmed(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "确认失败，请检查内容后重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <section className="card stack">
        <div>
          <p className="eyebrow">AI 饮食记录</p>
          <h1>拍照识别餐食</h1>
          <p>识别值只是估算。你确认或修改之前，不会计入今日看板。</p>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        {consent && !consent.granted && (
          <div className="consent-box">
            <p>照片会发送给 DeepSeek 进行识别，可能包含餐桌环境信息。只有你主动点击识别时才会发送；可在之后撤回同意。</p>
            <button type="button" onClick={grantConsent}>同意本功能的 AI 图片处理</button>
          </div>
        )}
        <label>
          拍照或选择照片（JPEG、PNG、WebP，最大 10 MB）
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            capture="environment"
            onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
          />
        </label>
        {preview && <div className="photo-preview" role="img" aria-label="待识别餐食照片预览" style={{ backgroundImage: `url(${preview})` }} />}
        <button type="button" onClick={uploadAndAnalyze} disabled={busy || !file || !consent?.granted}>
          {busy ? "识别中…" : photo ? "重新识别" : "上传并识别"}
        </button>
        <Link href="/meals/">AI 不可用？改用手工记录</Link>
      </section>

      {analysis?.result && !confirmed && (
        <form className="card stack" onSubmit={confirm}>
          <div>
            <p className="eyebrow">待确认草稿</p>
            <h2>检查识别结果</h2>
          </div>
          <p className="muted">整体可信度：{Math.round(analysis.result.overall_confidence * 100)}%</p>
          {analysis.result.warnings.length > 0 && (
            <ul className="warning-list">
              {analysis.result.warnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          )}
          <label>
            用餐时间
            <input type="datetime-local" required value={eatenAt} onChange={(event) => setEatenAt(event.target.value)} />
          </label>
          <label>
            餐次
            <select value={mealType} onChange={(event) => setMealType(event.target.value as typeof mealType)}>
              <option value="breakfast">早餐</option>
              <option value="lunch">午餐</option>
              <option value="dinner">晚餐</option>
              <option value="snack">加餐</option>
            </select>
          </label>
          {items.map((item, index) => (
            <div className="food-row stack" key={index}>
              <label>食物名称<input required value={item.name} onChange={(event) => updateItem(index, "name", event.target.value)} /></label>
              <label>份量<input type="number" min="0.01" step="0.01" required value={item.quantity} onChange={(event) => updateItem(index, "quantity", event.target.value)} /></label>
              <label>单位<input required value={item.unit} onChange={(event) => updateItem(index, "unit", event.target.value)} /></label>
              <label>热量（kcal）<input type="number" min="0" step="0.1" required value={item.kcal} onChange={(event) => updateItem(index, "kcal", event.target.value)} /></label>
              <div className="actions">
                <button type="button" className="danger" onClick={() => setItems((current) => current.filter((_, itemIndex) => itemIndex !== index))}>删除此项</button>
              </div>
            </div>
          ))}
          <button type="button" className="secondary" onClick={() => setItems((current) => [...current, { ...EMPTY_ITEM }])}>添加食物</button>
          <label>备注<textarea maxLength={2000} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
          <button type="submit" disabled={busy || items.length === 0}>{busy ? "保存中…" : "确认并计入看板"}</button>
        </form>
      )}

      {confirmed && (
        <section className="card stack">
          <p className="success" role="status">餐食已确认，并已计入今日看板。</p>
          <Link href="/">查看今日看板</Link>
          <button type="button" className="secondary" onClick={() => selectFile(null)}>继续拍照记录</button>
        </section>
      )}
      <Link href="/">返回首页</Link>
    </div>
  );
}
