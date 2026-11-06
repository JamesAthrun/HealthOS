"use client";

import { useCallback, useState } from "react";

import { ApiError } from "./api";

/** 统一处理“提交中 / 出错提示”；run 成功返回 true */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = useCallback(async (action: () => Promise<unknown>, fallback = "操作失败，请稍后重试") => {
    setBusy(true);
    setError("");
    try {
      await action();
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : fallback);
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  return { busy, error, setError, run };
}
