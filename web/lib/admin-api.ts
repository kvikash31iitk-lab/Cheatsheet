/* Admin-only API client. Server returns 403 unless the caller's email is in
 * ADMIN_EMAILS, so these helpers only work when the signed-in user is admin.
 */

async function req<T>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.json !== undefined) {
    headers.set('content-type', 'application/json');
  }
  const r = await fetch(path, {
    cache: 'no-store',
    ...init,
    headers,
    body: init.json !== undefined ? JSON.stringify(init.json) : init.body,
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(text || `${r.status} ${r.statusText}`);
  }
  if (r.status === 204) return undefined as T;
  return r.json();
}

// --- types ----------------------------------------------------------------

export type AdminSettings = {
  free_cheatsheets_per_day: number;
  free_books_per_day: number;
  cost_paise_per_30min_cheatsheet: number;
  cost_paise_per_30min_book: number;
  min_topup_paise: number;
  maintenance_mode: boolean;
  maintenance_message: string;
  authoring_provider: 'claude_code' | 'groq' | 'openai' | 'anthropic';
  whisper_backend: 'local' | 'groq' | 'openai';
  max_generations_per_hour_per_user: number;
  referral_credit_paise: number;
};

export type AdminUser = {
  id: string;
  email: string;
  name: string | null;
  picture_url: string | null;
  wallet_balance_paise: number;
  is_admin: boolean;
  is_banned: boolean;
  bypass_paid: boolean;
  daily_cheatsheets_override: number | null;
  daily_books_override: number | null;
  today_cheatsheets: number;
  today_books: number;
  total_generations: number;
  created_at: string | null;
  last_seen_at: string | null;
  referral_code: string | null;
};

export type AdminUserDetail = {
  user: AdminUser & {
    custom_prompt_cheatsheet: string | null;
    custom_prompt_book: string | null;
    referred_by_code: string | null;
  };
  transactions: Array<{
    id: string;
    kind: string;
    amount_paise: number;
    status: string;
    note: string | null;
    generation_id: string | null;
    created_at: string | null;
  }>;
  generations: Array<{
    id: string;
    kind: string;
    status: string;
    title: string | null;
    duration_seconds: number | null;
    cost_paise: number;
    was_free: boolean;
    error_message: string | null;
    created_at: string | null;
  }>;
  audit: Array<{
    id: string;
    admin_email: string;
    action: string;
    payload: Record<string, unknown> | null;
    created_at: string | null;
  }>;
};

export type AdminGeneration = {
  id: string;
  user_id: string;
  user_email: string;
  kind: string;
  url: string;
  video_id: string | null;
  title: string | null;
  channel: string | null;
  duration_seconds: number | null;
  status: string;
  step: string | null;
  progress: number;
  cost_paise: number;
  was_free: boolean;
  llm_cost_paise: number;
  transcription_cost_paise: number;
  error_message: string | null;
  created_at: string | null;
  completed_at: string | null;
};

export type AdminAuditEntry = {
  id: string;
  admin_email: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  payload: Record<string, unknown> | null;
  created_at: string | null;
};

export type AdminOverview = {
  users: { total: number; today: number; week: number };
  generations: {
    today: number;
    week: number;
    failed_week: number;
    running: number;
  };
  revenue_paise: { today: number; week: number; month: number };
  wallet_outstanding_paise: number;
  daily_series: Array<{ date: string; cheatsheet: number; book: number }>;
};

export type AdminBroadcast = {
  id: string;
  title: string;
  body: string;
  channels: string[];
  active: boolean;
  expires_at: string | null;
  created_at: string | null;
  created_by: string | null;
};

export type AdminPromo = {
  id: string;
  code: string;
  credit_paise: number;
  max_redemptions: number;
  times_redeemed: number;
  expires_at: string | null;
  active: boolean;
  created_at: string | null;
  created_by: string | null;
};

export type AdminBlock = {
  id: string;
  kind: 'channel' | 'keyword';
  pattern: string;
  reason: string | null;
  created_at: string | null;
  created_by: string | null;
};

export type AdminPayment = {
  id: string;
  user_id: string;
  user_email: string;
  amount_paise: number;
  status: string;
  razorpay_order_id: string | null;
  razorpay_payment_id: string | null;
  note: string | null;
  created_at: string | null;
};

export type AdminStorage = {
  disk: {
    total_bytes: number;
    used_bytes: number;
    free_bytes: number;
    work_dir_bytes: number;
  };
  rows: {
    users: number;
    generations: number;
    transactions: number;
    audit_log: number;
  };
};

export type AdminCookiesStatus =
  | { exists: false; proxy_configured: boolean }
  | {
      exists: true;
      proxy_configured: boolean;
      path: string;
      size_bytes: number;
      modified_at: string;
      valid_netscape: boolean;
      cookie_count: number;
      youtube_cookie_count: number;
    };

export type AdminYoutubeProbe = {
  ok: true;
  video_id: string;
  title: string;
  duration_seconds: number;
  proxy_configured: boolean;
};

// --- endpoints ------------------------------------------------------------

export const adminApi = {
  // overview
  overview: () => req<AdminOverview>('/api/admin/overview'),

  // settings
  getSettings: () => req<AdminSettings>('/api/admin/settings'),
  updateSettings: (patch: Partial<AdminSettings>) =>
    req<AdminSettings>('/api/admin/settings', { method: 'PUT', json: patch }),

  // users
  listUsers: (q = '', limit = 100, offset = 0) =>
    req<{ total: number; users: AdminUser[] }>(
      `/api/admin/users?q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}`,
    ),
  getUser: (id: string) => req<AdminUserDetail>(`/api/admin/users/${id}`),
  updateUser: (id: string, patch: Record<string, unknown>) =>
    req<{ ok: boolean; changes: unknown }>(`/api/admin/users/${id}`, {
      method: 'PUT',
      json: patch,
    }),
  creditUser: (id: string, amount_paise: number, reason: string) =>
    req<{ ok: boolean; new_balance_paise: number }>(
      `/api/admin/users/${id}/credit`,
      { method: 'POST', json: { amount_paise, reason } },
    ),

  // generations
  listGenerations: (status = '', limit = 100, offset = 0) =>
    req<{ total: number; generations: AdminGeneration[] }>(
      `/api/admin/generations?status=${encodeURIComponent(status)}&limit=${limit}&offset=${offset}`,
    ),
  retryGeneration: (id: string) =>
    req<{ ok: boolean }>(`/api/admin/generations/${id}/retry`, {
      method: 'POST',
    }),

  // audit
  audit: (limit = 200, offset = 0) =>
    req<{ total: number; entries: AdminAuditEntry[] }>(
      `/api/admin/audit?limit=${limit}&offset=${offset}`,
    ),

  // storage
  storage: () => req<AdminStorage>('/api/admin/health/storage'),

  // cookies
  cookiesStatus: () => req<AdminCookiesStatus>('/api/admin/cookies/status'),
  uploadCookies: (cookies_txt: string) =>
    req<{ ok: boolean; path: string; bytes: number }>('/api/admin/cookies', {
      method: 'POST',
      json: { cookies_txt },
    }),
  probeYoutube: (url: string) =>
    req<AdminYoutubeProbe>('/api/admin/youtube/probe', {
      method: 'POST',
      json: { url },
    }),

  // broadcasts
  listBroadcasts: () => req<AdminBroadcast[]>('/api/admin/broadcasts'),
  createBroadcast: (input: {
    title: string;
    body: string;
    channels: Array<'banner' | 'telegram'>;
    expires_in_hours?: number;
  }) =>
    req<{ id: string }>('/api/admin/broadcasts', {
      method: 'POST',
      json: input,
    }),
  deactivateBroadcast: (id: string) =>
    req<{ ok: boolean }>(`/api/admin/broadcasts/${id}/deactivate`, {
      method: 'POST',
    }),

  // promos
  listPromos: () => req<AdminPromo[]>('/api/admin/promos'),
  createPromo: (input: {
    code: string;
    credit_paise: number;
    max_redemptions: number;
    expires_in_days?: number;
  }) => req<{ id: string; code: string }>('/api/admin/promos', { method: 'POST', json: input }),
  deactivatePromo: (id: string) =>
    req<{ ok: boolean }>(`/api/admin/promos/${id}/deactivate`, {
      method: 'POST',
    }),

  // blocks
  listBlocks: () => req<AdminBlock[]>('/api/admin/blocks'),
  createBlock: (input: { kind: 'channel' | 'keyword'; pattern: string; reason?: string }) =>
    req<{ id: string }>('/api/admin/blocks', { method: 'POST', json: input }),
  deleteBlock: (id: string) =>
    req<{ ok: boolean }>(`/api/admin/blocks/${id}`, { method: 'DELETE' }),

  // failed payments
  failedPayments: () => req<AdminPayment[]>('/api/admin/payments/failed'),

  // UPSC digest issues
  listUpscIssues: (limit = 30, offset = 0) =>
    req<{ issues: UpscIssue[]; limit: number; offset: number }>(
      `/api/admin/upsc/issues?limit=${limit}&offset=${offset}`,
    ),
  getUpscIssue: (id: string) =>
    req<UpscIssue & { markdown: string | null }>(
      `/api/admin/upsc/issues/${id}`,
    ),
  uploadUpscIssue: (form: FormData) =>
    req<UpscIssue>('/api/admin/upsc/upload', {
      method: 'POST',
      body: form,
    }),
  patchUpscIssue: (
    id: string,
    patch: {
      title?: string;
      style?: UpscStyle;
      markdown?: string;
      source?: string;
    },
  ) =>
    req<UpscIssue & { markdown: string | null }>(`/api/admin/upsc/issues/${id}`, {
      method: 'PATCH',
      json: patch,
    }),
  reauthorUpscIssue: (id: string) =>
    req<UpscIssue>(`/api/admin/upsc/issues/${id}/reauthor`, { method: 'POST' }),
  publishUpscIssue: (id: string) =>
    req<UpscIssue>(`/api/admin/upsc/issues/${id}/publish`, { method: 'POST' }),
  unpublishUpscIssue: (id: string) =>
    req<UpscIssue>(`/api/admin/upsc/issues/${id}/unpublish`, { method: 'POST' }),
  deleteUpscIssue: (id: string) =>
    req<{ deleted: string }>(`/api/admin/upsc/issues/${id}`, {
      method: 'DELETE',
    }),
  reseedPyq: (years: string, stages: Array<'prelims' | 'mains'>) =>
    req<{ queued: string }>('/api/admin/upsc/pyq/reseed', {
      method: 'POST',
      json: { years, stages },
    }),

  // UPSC video
  getVoices: (engine: VideoConfig['engine'], lang: VideoConfig['lang']) =>
    req<{ voices: VoiceOption[]; gemini_billing_active: boolean }>(
      `/api/admin/upsc/voices?engine=${encodeURIComponent(engine)}&lang=${encodeURIComponent(lang)}`,
    ).then((r) => r.voices),
  previewVoice: (input: {
    engine: VideoConfig['engine'];
    voice: string;
    lang: VideoConfig['lang'];
    text: string;
  }) =>
    fetch('/api/admin/upsc/voice-preview', {
      method: 'POST',
      cache: 'no-store',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(input),
    }).then(async (r) => {
      if (!r.ok) {
        const text = await r.text();
        throw new Error(text || `${r.status} ${r.statusText}`);
      }
      return r.blob();
    }),
  /* Kick BOTH the English and Hindi script jobs in one call. Returns both job
   * ids immediately; poll each with getScriptJob() and let the user toggle
   * between the two finished scripts (no re-generation needed to switch). */
  generateScript: (id: string) =>
    req<ScriptJobPair>(
      `/api/admin/upsc/issues/${id}/script`,
      { method: 'POST' },
    ),
  /* Poll one script job (read-only). 404 (unknown job) throws via req(). */
  getScriptJob: (jobId: string) =>
    req<ScriptJobStatus>(`/api/admin/upsc/script/${jobId}`),
  saveScript: (id: string, sections: NarrationSection[], confirmed: boolean) =>
    req<{ ok: boolean }>(`/api/admin/upsc/issues/${id}/script`, {
      method: 'PATCH',
      json: { sections, confirmed },
    }),
  makeVideo: (id: string, config: VideoConfig) =>
    req<UpscIssue>(`/api/admin/upsc/issues/${id}/make-video`, {
      method: 'POST',
      json: { config },
    }),
  publishYoutube: (
    id: string,
    meta: {
      title: string;
      description: string;
      tags: string[];
      privacy: VideoConfig['privacy'];
    },
  ) =>
    req<{ youtube_url: string }>(`/api/admin/upsc/issues/${id}/youtube`, {
      method: 'POST',
      json: meta,
    }),
  getVideoDefaults: () =>
    req<VideoDefaults>('/api/admin/upsc/video-defaults'),
  putVideoDefaults: (defaults: VideoDefaults) =>
    req<{ ok: boolean }>('/api/admin/upsc/video-defaults', {
      method: 'PUT',
      json: { defaults },
    }),
  videoUrl: (id: string) => `/api/admin/upsc/video/${id}`,
  thumbUrl: (id: string) => `/api/admin/upsc/issues/${id}/thumb`,
};

// UPSC types --------------------------------------------------------------

export type UpscStyle =
  | 'academic'
  | 'dense'
  | 'dense_tight'
  | 'coaching'
  | 'magazine';

export type UpscStatus =
  | 'uploaded'
  | 'extracting'
  | 'classifying'
  | 'authoring'
  | 'rendering'
  | 'preview'
  | 'published'
  | 'video_rendering'
  | 'video_ready'
  | 'error';

// UPSC video types --------------------------------------------------------

export type VoiceOption = {
  id: string;
  label: string;
  rank: number;
  is_default: boolean;
};

export type NarrationSection = {
  section_id: string;
  label: string;
  text: string;
  est_seconds: number;
};

export type ScriptJobState = 'pending' | 'processing' | 'done' | 'failed';

/** Returned by POST .../script (async kick) — both languages at once. */
export type ScriptJobPair = {
  en_job_id: string;
  hi_job_id: string;
  status: ScriptJobState;
};

/** Returned by GET .../script/{job_id} (poll). Locked contract shape.
 *  `result` carries structured `sections` (not a single `script` string),
 *  matching what the editor renders. */
export type ScriptJobStatus = {
  status: ScriptJobState;
  progress: number; // 0–100, coarse: 0 pending, 50 processing, 100 done/failed
  result: { sections: NarrationSection[] } | null;
  error: string | null;
};

export type VideoConfig = {
  engine: 'gemini' | 'chirp';
  voice: string;
  lang: 'hi' | 'en';
  slide_style: 'digest' | 'clean' | 'animated';
  theme: string;
  privacy: 'public' | 'unlisted' | 'private';
  sample?: boolean;
};

export type VideoDefaults = VideoConfig & {
  auto_publish: boolean;
  auto_generate_on_upload: boolean;
  title_template: string;
  description_template: string;
};

export type UpscIssue = {
  id: string;
  issue_date: string;
  source: string;
  title: string;
  style: UpscStyle;
  status: UpscStatus;
  error_message: string | null;
  article_count: number;
  summary: string | null;
  has_output_pdf: boolean;
  has_cover_thumb: boolean;
  created_at: string | null;
  published_at: string | null;
  llm_tokens_in: number;
  llm_tokens_out: number;
  llm_cost_paise: number;
  extract_seconds: number | null;
  classify_seconds: number | null;
  author_seconds: number | null;
  render_seconds: number | null;
  video_status: string | null;
  video_progress: string | null;
  video_path: string | null;
  youtube_id: string | null;
  youtube_url: string | null;
  narration_script: string | null;
  script_confirmed: boolean;
  video_config: string | null;
};
