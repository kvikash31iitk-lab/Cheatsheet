export type JobKind = 'cheatsheet' | 'book' | 'mcq';

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
    lower.includes('members only')
  ) {
    return 'This video is members-only. The YouTube account in the uploaded cookies must be a paid member of this channel. Refresh the cookies only if that account has access.';
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
    lower.includes('unauthenticated') ||
    lower.includes('invalid authentication credentials') ||
    lower.includes('api_key') ||
    lower.includes('invalid api key')
  ) {
    return 'AI authoring service encountered an authentication issue. Please try again or contact support.';
  }

  if (
    lower.includes('cookies are no longer valid') ||
    lower.includes('cookies have expired') ||
    lower.includes('cookies have likely been rotated') ||
    (lower.includes('youtube') && lower.includes('cookie'))
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

  if (
    lower.includes('authoring_provider') ||
    lower.includes('notimplementederror') ||
    lower.includes('authoring failed') ||
    lower.includes('cli login or quota') ||
    lower.includes('rate_limit') ||
    lower.includes('tokens per minute') ||
    lower.includes('tpm') ||
    lower.includes('all groq fallback') ||
    lower.includes('request too large') ||
    lower.includes('groq')
  ) {
    return 'AI generation service is currently experiencing high load or limits. Please try again shortly.';
  }

  // Explicit YouTube download failures
  if (
    lower.includes('yt-dlp') ||
    lower.includes('youtube-dl') ||
    lower.includes('player responses') ||
    lower.includes('metadata failed') ||
    lower.includes('could not extract video')
  ) {
    return 'YouTube could not be reached right now. Please try again shortly.';
  }

  // Keep short application messages, sanitize unhandled tracebacks
  if (
    message.length > 260 ||
    /(?:traceback|runtimeerror|\bwarning:|\berror:)/i.test(message)
  ) {
    return 'Generation encountered a processing error. Please try again.';
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

export async function createNewEngineJob(url: string): Promise<{ id: string }> {
  const r = await fetch('/api/new/generate', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  if (!r.ok) {
    throw new Error(await apiErrorMessage(r, 'Could not start the new engine.'));
  }
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

export async function createPlaylistJob(
  playlist_url: string,
  kind: JobKind = 'cheatsheet',
  delay_seconds = 2.0,
  max_videos?: number,
  concurrency = 3,
): Promise<{ id: string }> {
  const res = await fetch('/api/playlist/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ playlist_url, kind, delay_seconds, max_videos, concurrency }),
  });
  if (!res.ok) throw new Error(await apiErrorMessage(res, 'Failed to start playlist job'));
  return res.json();
}


export async function getPlaylistJob(id: string): Promise<any> {
  const res = await fetch(`/api/playlist/status/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(await apiErrorMessage(res, 'Failed to fetch playlist status'));
  return res.json();
}

export async function retryPlaylistJob(id: string): Promise<{ id: string }> {
  const res = await fetch(`/api/playlist/retry/${encodeURIComponent(id)}`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(await apiErrorMessage(res, 'Failed to retry playlist job'));
  return res.json();
}

export async function stopPlaylistJob(id: string): Promise<{ id: string; status: string }> {
  const res = await fetch(`/api/playlist/stop/${encodeURIComponent(id)}`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(await apiErrorMessage(res, 'Failed to stop playlist job'));
  return res.json();
}

export interface PlaylistItem {
  item_key: string;
  title: string;
  status?: string;
  current_subtask?: string;
  video_id?: string;
  has_pdf: boolean;
  error?: string;
  orig_idx?: number;
}

export interface PlaylistJob {
  id: string;
  title?: string;
  playlist_title?: string;
  playlist_url: string;
  status: string;
  active_video?: any;
  created_at?: string;
  total_videos: number;
  summary?: any;
  items: PlaylistItem[];
}

export async function listPlaylists(): Promise<PlaylistJob[]> {
  const res = await fetch('/api/playlist/list');
  if (!res.ok) throw new Error(await apiErrorMessage(res, 'Failed to fetch playlists'));
  return res.json();
}






