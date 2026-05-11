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
  free_cheatsheets_per_day: number;
  free_books_per_day: number;
  wallet_balance_paise: number;
  referral_code: string | null;
  bypass_paid: boolean;
  cost_paise_per_30min: { cheatsheet: number; book: number };
  min_topup_paise: number;
  maintenance: { active: boolean; message: string };
  banner: { id: string; title: string; body: string } | null;
};

export async function redeemPromo(code: string): Promise<{
  ok: boolean;
  credited_paise: number;
  new_balance_paise: number;
}> {
  const r = await fetch('/api/promos/redeem', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ code }),
  });
  if (!r.ok) throw new Error((await r.text()) || `redeem failed: ${r.status}`);
  return r.json();
}

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

export type Preview = {
  video_id: string;
  title: string;
  duration_seconds: number;
  thumbnail_url: string;
  cost_paise: { cheatsheet: number; book: number };
};

export async function getPreview(url: string): Promise<Preview> {
  const r = await fetch('/api/preview', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(body || `preview failed: ${r.status}`);
  }
  return r.json();
}

// --- wallet ----------------------------------------------------------------

export type Transaction = {
  id: string;
  kind: 'topup' | 'spend' | 'refund';
  amount_paise: number;
  status: 'pending' | 'success' | 'failed';
  note: string | null;
  generation_id: string | null;
  created_at: string | null;
};

export type WalletOrder = {
  order_id: string;
  amount_paise: number;
  key_id: string;
  currency: string;
};

export async function createWalletOrder(amount_paise: number): Promise<WalletOrder> {
  const r = await fetch('/api/wallet/order', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ amount_paise }),
  });
  if (!r.ok) throw new Error((await r.text()) || `order failed: ${r.status}`);
  return r.json();
}

export async function verifyWalletPayment(payload: {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}): Promise<{ balance_paise: number; credited?: number; already?: boolean }> {
  const r = await fetch('/api/wallet/verify', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error((await r.text()) || `verify failed: ${r.status}`);
  return r.json();
}

export async function getTransactions(): Promise<Transaction[]> {
  const r = await fetch('/api/wallet/transactions', { cache: 'no-store' });
  if (!r.ok) throw new Error(`transactions failed: ${r.status}`);
  return r.json();
}
