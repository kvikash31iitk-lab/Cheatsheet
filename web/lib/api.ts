export type JobKind = 'cheatsheet' | 'book';

// Opt-in PDF enhancements selected on the generate form. Each flag drives a
// piece of the prompt + a piece of the PDF builder — see bot/cache.py and
// bot/author.py for the full taxonomy. Keep this union in sync with
// FEATURE_ORDER on the backend; extra/unknown values are silently dropped
// server-side so this is safe to extend.
export type FeatureFlag =
  | 'summary'    // cover-page summary card
  | 'tldr'       // `> [!tldr]` callouts at the start of each section
  | 'qna'        // `## Self-Test` appendix with `> [!q]` Q&A callouts
  | 'mermaid'    // mindmap + flowchart pages (rendered via mmdc)
  | 'chapters';  // chapter index page (book) / QR code (both)

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
  features?: FeatureFlag[];
  created_at: string;
  status: JobStatus;
  meta?: JobMeta;
};

function messageFromPayload(value: unknown): string | null {
  if (typeof value === 'string') return value.trim() || null;

  if (Array.isArray(value)) {
    const messages = value
      .map((item) => messageFromPayload(item))
      .filter((item): item is string => Boolean(item));
    return messages.length ? messages.join(' ') : null;
  }

  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    for (const key of ['detail', 'message', 'error', 'msg']) {
      const message = messageFromPayload(record[key]);
      if (message) return message;
    }
  }

  return null;
}

function messageFromText(text: string): string | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  try {
    return messageFromPayload(JSON.parse(trimmed));
  } catch {
    return trimmed;
  }
}

/** Read FastAPI's { detail: ... } response shape without showing raw JSON. */
export async function apiErrorMessage(response: Response, fallback: string): Promise<string> {
  return messageFromText(await response.text()) ?? fallback;
}

/** Extract a useful message from an Error, including legacy Errors containing JSON text. */
export function errorMessage(error: unknown, fallback = 'Something went wrong.'): string {
  const raw = error instanceof Error ? error.message : typeof error === 'string' ? error : '';
  return messageFromText(raw) ?? fallback;
}

/** Convert verbose yt-dlp diagnostics into safe, actionable copy for users. */
export function friendlyGenerationError(error: unknown): string {
  const rawMessage = errorMessage(error, 'Generation could not be completed. Please try again.');
  const message = rawMessage
    .replace(/^Could not read (?:URL|this video):\s*/i, '')
    .replace(/^yt-dlp metadata failed:\s*/i, '');
  const lower = message.toLowerCase();

  if (
    lower.includes('video unavailable') ||
    lower.includes('this video is unavailable') ||
    lower.includes('has been removed') ||
    lower.includes('private video')
  ) {
    return 'This video is unavailable, private, deleted, or restricted. Check that it plays on YouTube and try again.';
  }

  if (
    lower.includes('members-only') ||
    lower.includes('members only') ||
    lower.includes('age-restricted') ||
    lower.includes('age restricted') ||
    lower.includes('login required')
  ) {
    return 'This video requires restricted YouTube access and cannot be processed.';
  }

  if (
    lower.includes('no transcript') ||
    lower.includes('transcript unavailable') ||
    lower.includes('subtitles are disabled') ||
    lower.includes('could not retrieve a transcript') ||
    lower.includes('no usable transcript')
  ) {
    return 'No usable transcript was found. Try a video with captions or clear spoken audio.';
  }

  if (
    lower.includes('cookies are no longer valid') ||
    lower.includes('cookies have expired') ||
    lower.includes('cookies have likely been rotated') ||
    (lower.includes('cookie') && lower.includes('authentication'))
  ) {
    return 'YouTube access needs to be refreshed. Please try again later or contact support.';
  }

  if (
    lower.includes('http error 429') ||
    lower.includes('http error 403') ||
    lower.includes('too many requests') ||
    lower.includes('rate-limit') ||
    lower.includes('rate limit') ||
    lower.includes('anti-bot') ||
    lower.includes('sign in to confirm you') ||
    lower.includes('not a bot')
  ) {
    return 'YouTube temporarily blocked this request. Please wait a few minutes and try again.';
  }

  if (
    lower.includes('unsupported url') ||
    lower.includes('invalid youtube') ||
    lower.includes('not a valid youtube')
  ) {
    return 'Enter a valid YouTube video link and try again.';
  }

  // Keep short application messages (billing, maintenance, limits, etc.),
  // but never fill the UI with downloader diagnostics or stack traces.
  if (
    message.length > 260 ||
    /(?:yt-dlp|youtube-dl|traceback|runtimeerror|metadata failed|player responses|\bwarning:|\berror:)/i.test(message)
  ) {
    return 'YouTube could not be reached right now. Please try again shortly.';
  }

  return message;
}

export async function createJob(
  url: string,
  kind: JobKind,
  features: FeatureFlag[] = [],
): Promise<{ id: string }> {
  const r = await fetch('/api/generate', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ url, kind, features }),
  });
  if (!r.ok) throw new Error(await apiErrorMessage(r, 'Could not start generation.'));
  return r.json();
}

export async function getJob(id: string): Promise<Job> {
  const r = await fetch(`/api/jobs/${id}`);
  if (!r.ok) throw new Error(await apiErrorMessage(r, 'Could not load generation.'));
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
    throw new Error(await apiErrorMessage(r, 'Could not read this video.'));
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

export type TelegramLinkUrl = {
  url: string;
  expires_in_seconds: number;
  currently_linked: boolean;
};

export async function getTelegramLinkUrl(): Promise<TelegramLinkUrl> {
  const r = await fetch('/api/telegram/link-url', { cache: 'no-store' });
  if (!r.ok) throw new Error((await r.text()) || `link-url failed: ${r.status}`);
  return r.json();
}

export async function unlinkTelegram(): Promise<{ ok: boolean }> {
  const r = await fetch('/api/telegram/unlink', { method: 'POST' });
  if (!r.ok) throw new Error((await r.text()) || `unlink failed: ${r.status}`);
  return r.json();
}
