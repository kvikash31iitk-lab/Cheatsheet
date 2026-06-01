/* Public UPSC API — no auth, browser-cached, safe to call from server
 * components too (no cookies needed). */

export type UpscIssueCard = {
  date: string;
  title: string;
  source: string;
  summary: string | null;
  article_count: number;
  published_at: string | null;
};

export type UpscIssueDetail = UpscIssueCard & {
  pdf_url: string;
  thumb_url: string;
};

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(path, { cache: 'no-store', ...opts });
  if (!r.ok) {
    if (r.status === 404) throw Object.assign(new Error('not-found'), { status: 404 });
    throw new Error(`${r.status} ${r.statusText}`);
  }
  return r.json();
}

export const upscApi = {
  list: (limit = 30, offset = 0) =>
    req<{ issues: UpscIssueCard[]; limit: number; offset: number }>(
      `/api/public/upsc/issues?limit=${limit}&offset=${offset}`,
    ),
  get: (date: string) => req<UpscIssueDetail>(`/api/public/upsc/issues/${date}`),
};

// Server-side helper — same shape but uses the absolute API URL when called
// from a server component, so SSR works.
export async function serverFetchUpscList(
  limit = 12,
): Promise<UpscIssueCard[]> {
  const base = process.env.INTERNAL_API_BASE ?? 'http://127.0.0.1:8000';
  try {
    const r = await fetch(`${base}/api/public/upsc/issues?limit=${limit}`, {
      cache: 'no-store',
    });
    if (!r.ok) return [];
    const data = (await r.json()) as { issues: UpscIssueCard[] };
    return data.issues;
  } catch {
    return [];
  }
}

export async function serverFetchUpscIssue(
  date: string,
): Promise<UpscIssueDetail | null> {
  const base = process.env.INTERNAL_API_BASE ?? 'http://127.0.0.1:8000';
  try {
    const r = await fetch(`${base}/api/public/upsc/issues/${date}`, {
      cache: 'no-store',
    });
    if (!r.ok) return null;
    return (await r.json()) as UpscIssueDetail;
  } catch {
    return null;
  }
}
