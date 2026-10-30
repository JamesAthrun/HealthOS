"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, ApiError, type Me } from "./api";

// 读取当前登录用户；未登录时跳转到登录页
export function useMe(): Me | null {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    api<Me>("/me")
      .then(setMe)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/login/");
      });
  }, [router]);

  return me;
}
