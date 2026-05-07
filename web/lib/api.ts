export type JobKind = 'cheatsheet' | 'book';

export type JobStatus =
  | { state: 'queued'; position?: number }
  | { state: 'running'; step: string; progress: number }
  | { state: 'done'; pdf_url: string; markdown: string; meta: JobMeta }
  | { state: 'error'; message: string };

export type JobMeta = {
  video_id: string;
  title: string;
  duration_seconds: number;
  channel?: string;
  thumbnail_url?: string;
};

export type Job = {
  id: string;
  kind: JobKind;
  url: string;
  created_at: string;
  status: JobStatus;
  meta?: JobMeta;
};

export async function createJob(url: string, kind: JobKind): Promise<{ id: string }> {
  const r = await fetch('/api/generate', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ url, kind }),
  });
  if (!r.ok) throw new Error(`generate failed: ${r.status} ${await r.text()}`);
  return r.json();
}

export async function getJob(id: string): Promise<Job> {
  const r = await fetch(`/api/jobs/${id}`);
  if (!r.ok) throw new Error(`get job failed: ${r.status}`);
  return r.json();
}

export type Me = {
  id: string;
  email: string;
  name: string | null;
  picture_url: string | null;
  is_admin: boolean;
  free_cheatsheets_left: number;
  free_books_left: number;
  wallet_balance_paise: number;
};

export async function getMe(): Promise<Me> {
  const r = await fetch('/api/me', { cache: 'no-store' });
  if (!r.ok) throw new Error(`get me failed: ${r.status}`);
  return r.json();
}

export async function getLibrary(): Promise<Job[]> {
  const r = await fetch('/api/library', { cache: 'no-store' });
  if (!r.ok) throw new Error(`get library failed: ${r.status}`);
  return r.json();
}
