export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: options.method ?? "GET",
    credentials: "same-origin",
    headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!res.ok) {
    let message = "请求失败，请稍后再试";
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) message = "输入内容不符合要求";
    } catch {
      // 非 JSON 响应，使用默认提示
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export type Me = {
  id: string;
  username: string;
  display_name: string;
  is_admin: boolean;
  timezone: string;
  locale: string;
};

export type AuditEvent = {
  id: string;
  event_type: string;
  outcome: string;
  ip_address: string | null;
  created_at: string;
};
