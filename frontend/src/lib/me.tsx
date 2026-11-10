"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

import { api, ApiError, type Me } from "./api";

type MeState = { me: Me | null; setMe: (me: Me | null) => void };

const MeContext = createContext<MeState>({ me: null, setMe: () => undefined });

/** 只在首次进入（或重新登录）时请求一次 /me，所有页面共用，避免每页都闪“加载中” */
export function MeProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const onLogin = pathname.startsWith("/login") || pathname.startsWith("/register");

  useEffect(() => {
    if (onLogin || me) return;
    let active = true;
    api<Me>("/me")
      .then((data) => { if (active) setMe(data); })
      .catch((err) => {
        if (active && err instanceof ApiError && err.status === 401) router.replace("/login/");
      });
    return () => { active = false; };
  }, [onLogin, me, router]);

  return <MeContext.Provider value={{ me, setMe }}>{children}</MeContext.Provider>;
}

/** 当前登录用户；尚未加载完成时为 null */
export function useMe(): Me | null {
  return useContext(MeContext).me;
}

export function useSetMe() {
  return useContext(MeContext).setMe;
}
