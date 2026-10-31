"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { api, ApiError, type Me } from "@/lib/api";
import { useMe } from "@/lib/useMe";

type Profile = {
  birth_year: number | null;
  sex: "male" | "female" | null;
  height_cm: number | null;
  weight_kg: number | null;
  activity_level: "sedentary" | "light" | "moderate" | "active" | null;
  dietary_preferences: string | null;
  allergies: string | null;
  daily_kcal_target: number | null;
};

type KcalReference = {
  maintenance_kcal: number;
  weight_loss_kcal: number | null;
  bmi: number;
  formula: string;
  notice: string;
};

const EMPTY: Record<keyof Profile, string> = {
  birth_year: "",
  sex: "",
  height_cm: "",
  weight_kg: "",
  activity_level: "",
  dietary_preferences: "",
  allergies: "",
  daily_kcal_target: "",
};

export default function ProfilePage() {
  const me = useMe();
  if (!me) return <p>加载中…</p>;
  return <ProfileForm key={me.id} me={me} />;
}

function ProfileForm({ me }: { me: Me }) {
  const [form, setForm] = useState({ ...EMPTY });
  const [reference, setReference] = useState<KcalReference | null>(null);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api<Profile>("/profile")
      .then((profile) => {
        setForm(
          Object.fromEntries(
            Object.entries(profile)
              .filter(([key]) => key in EMPTY)
              .map(([key, value]) => [key, value === null ? "" : String(value)]),
          ) as Record<keyof Profile, string>,
        );
      })
      .catch((err) => {
        if (!(err instanceof ApiError && err.status === 404)) setError("档案加载失败，请稍后重试");
      });
  }, []);

  function set(field: keyof Profile, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setDone(false);
    setSubmitting(true);
    const numberOrNull = (value: string) => (value ? Number(value) : null);
    try {
      await api<Profile>("/profile", {
        method: "PUT",
        body: {
          birth_year: numberOrNull(form.birth_year),
          sex: form.sex || null,
          height_cm: numberOrNull(form.height_cm),
          weight_kg: numberOrNull(form.weight_kg),
          activity_level: form.activity_level || null,
          dietary_preferences: form.dietary_preferences || null,
          allergies: form.allergies || null,
          daily_kcal_target: numberOrNull(form.daily_kcal_target),
        },
      });
      setDone(true);
      try {
        setReference(await api<KcalReference>("/profile/kcal-reference"));
      } catch {
        setReference(null);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "网络异常，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card stack" onSubmit={onSubmit}>
      <h1>{me.display_name}的健康档案</h1>
      <p>用于计算个人参考值；所有内容仅供本人查看。</p>
      {error && <p className="error" role="alert">{error}</p>}
      {done && <p className="success" role="status">档案已保存</p>}
      <label>
        出生年份（仅限 18 岁以上）
        <input type="number" min="1900" max={new Date().getFullYear() - 18} value={form.birth_year} onChange={(e) => set("birth_year", e.target.value)} />
      </label>
      <label>
        性别（用于公式）
        <select value={form.sex} onChange={(e) => set("sex", e.target.value)}>
          <option value="">暂不填写</option>
          <option value="female">女</option>
          <option value="male">男</option>
        </select>
      </label>
      <label>
        身高（厘米）
        <input type="number" min="50" max="250" step="0.1" value={form.height_cm} onChange={(e) => set("height_cm", e.target.value)} />
      </label>
      <label>
        体重（公斤）
        <input type="number" min="20" max="500" step="0.1" value={form.weight_kg} onChange={(e) => set("weight_kg", e.target.value)} />
      </label>
      <label>
        活动水平
        <select value={form.activity_level} onChange={(e) => set("activity_level", e.target.value)}>
          <option value="">暂不填写</option>
          <option value="sedentary">久坐，较少运动</option>
          <option value="light">轻度活动</option>
          <option value="moderate">中等活动</option>
          <option value="active">较高活动</option>
        </select>
      </label>
      <label>
        饮食偏好
        <textarea value={form.dietary_preferences} maxLength={1000} onChange={(e) => set("dietary_preferences", e.target.value)} />
      </label>
      <label>
        过敏信息
        <textarea value={form.allergies} maxLength={1000} onChange={(e) => set("allergies", e.target.value)} />
      </label>
      <label>
        每日热量目标（可在看到参考值后填写）
        <input type="number" min="1000" max="10000" value={form.daily_kcal_target} onChange={(e) => set("daily_kcal_target", e.target.value)} />
      </label>
      {reference && (
        <div className="reference">
          <strong>每日维持参考：约 {reference.maintenance_kcal} kcal</strong>
          <p>BMI：{reference.bmi}</p>
          {reference.weight_loss_kcal && <p>温和减重参考：约 {reference.weight_loss_kcal} kcal</p>}
          <small>{reference.formula} · {reference.notice}</small>
        </div>
      )}
      <button type="submit" disabled={submitting}>{submitting ? "保存中…" : "保存并计算参考值"}</button>
      <Link href="/">返回首页</Link>
    </form>
  );
}
