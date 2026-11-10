export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** 网络卡住时 fetch 不会自己结束，按钮会一直转；超时后中止并提示 */
async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch {
    if (controller.signal.aborted) throw new ApiError(0, "网络超时，请检查网络后重试");
    throw new ApiError(0, "网络连接失败，请检查网络后重试");
  } finally {
    clearTimeout(timer);
  }
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; timeoutMs?: number } = {},
): Promise<T> {
  const res = await fetchWithTimeout(`/api${path}`, {
    method: options.method ?? "GET",
    credentials: "same-origin",
    headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  }, options.timeoutMs ?? 20_000);
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

export async function uploadApi<T>(path: string, file: File): Promise<T> {
  const res = await fetchWithTimeout(`/api${path}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  }, 60_000);
  if (!res.ok) {
    let message = "照片上传失败，请稍后再试";
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      // 非 JSON 响应，使用默认提示
    }
    throw new ApiError(res.status, message);
  }
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
