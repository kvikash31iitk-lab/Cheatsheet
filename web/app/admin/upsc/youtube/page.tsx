'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AdminShell, PageHeader, Section, Input, Select, Textarea, Toggle } from '@/components/admin-shell';
import { Tag } from '@/components/ui';
import {
  adminApi,
  type UpscIssue,
  type UpscStatus,
  type UpscStyle,
  type VoiceOption,
  type NarrationSection,
  type VideoConfig,
  type VideoDefaults,
} from '@/lib/admin-api';

/* ------------------------------------------------------------------ *
 *  Status maps (mirror the digest pages, extended for video states)   *
 * ------------------------------------------------------------------ */

const STATUS_LABEL: Record<UpscStatus, string> = {
  uploaded: 'Queued',
  extracting: 'Extracting (OCR)',
  classifying: 'Classifying',
  authoring: 'Authoring',
  rendering: 'Rendering',
  preview: 'Preview',
  published: 'Published',
  video_rendering: 'Rendering video',
  video_ready: 'Video ready',
  error: 'Error',
};

const STATUS_TONE: Record<UpscStatus, 'neutral' | 'accent' | 'mint' | 'gold' | 'rose'> = {
  uploaded: 'neutral',
  extracting: 'accent',
  classifying: 'accent',
  authoring: 'accent',
  rendering: 'accent',
  preview: 'gold',
  published: 'mint',
  video_rendering: 'accent',
  video_ready: 'mint',
  error: 'rose',
};

/* video_status values written by the backend (none|queued|rendering|uploading|ready|error) */
type VideoStatus = 'none' | 'queued' | 'rendering' | 'uploading' | 'ready' | 'error';

const VIDEO_STATUS_LABEL: Record<VideoStatus, string> = {
  none: 'Not started',
  queued: 'Queued',
  rendering: 'Rendering',
  uploading: 'Uploading',
  ready: 'Ready',
  error: 'Error',
};

const VIDEO_STATUS_TONE: Record<VideoStatus, 'neutral' | 'accent' | 'gold' | 'mint' | 'rose'> = {
  none: 'neutral',
  queued: 'neutral',
  rendering: 'accent',
  uploading: 'gold',
  ready: 'mint',
  error: 'rose',
};

/* The pipeline stages we render as a progress strip. The backend reports the
 * current stage via video_progress (a free-text label) — we match loosely. */
const VIDEO_STAGES = ['slides', 'tts', 'stitch', 'upload'] as const;
const VIDEO_STAGE_LABEL: Record<(typeof VIDEO_STAGES)[number], string> = {
  slides: 'Slides',
  tts: 'Voiceover',
  stitch: 'Stitch',
  upload: 'Upload',
};

const VIDEO_IN_FLIGHT: VideoStatus[] = ['queued', 'rendering', 'uploading'];

/* ------------------------------------------------------------------ *
 *  Variant catalogues (display-only metadata for the cards/radios)    *
 * ------------------------------------------------------------------ */

const ENGINES: Array<{ id: VideoConfig['engine']; label: string; sub: string }> = [
  { id: 'gemini', label: 'Gemini', sub: 'expressive teacher' },
  { id: 'chirp', label: 'Chirp3-HD', sub: 'vikash voice' },
];

const LANGS: Array<{ id: VideoConfig['lang']; label: string; sub: string }> = [
  { id: 'hi', label: 'Hindi', sub: 'Hinglish · Devanagari' },
  { id: 'en', label: 'English', sub: 'en-IN' },
];

const SLIDE_STYLES: Array<{
  id: VideoConfig['slide_style'];
  label: string;
  sub: string;
}> = [
  { id: 'clean', label: 'Branded deck (16:9)', sub: 'polished slides from the digest — default' },
  { id: 'digest', label: 'Digest pages', sub: 'rendered cheatsheet, letterboxed 1920×1080' },
  { id: 'animated', label: 'Animated', sub: 'motion-graphics (coming soon)' },
];

const THEMES = ['amber', 'slate', 'forest', 'indigo', 'rose', 'mono'] as const;

const PRIVACIES: Array<{ id: VideoConfig['privacy']; label: string }> = [
  { id: 'private', label: 'Private' },
  { id: 'unlisted', label: 'Unlisted' },
  { id: 'public', label: 'Public' },
];

const PREVIEW_SAMPLE: Record<VideoConfig['lang'], string> = {
  hi: 'नमस्ते, यह आज के UPSC डाइजेस्ट की एक झलक है।',
  en: 'Hello, this is a quick sample of today’s UPSC digest narration.',
};

const DEFAULT_CONFIG: VideoConfig = {
  engine: 'gemini',
  voice: '',
  lang: 'hi',
  slide_style: 'clean',
  theme: 'amber',
  privacy: 'unlisted',
};

/* ------------------------------------------------------------------ *
 *  Small helpers                                                      *
 * ------------------------------------------------------------------ */

function formatDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

function fmtSeconds(secs: number): string {
  if (!isFinite(secs) || secs <= 0) return '0s';
  if (secs < 60) return `${Math.round(secs)}s`;
  const m = Math.floor(secs / 60);
  const s = Math.round(secs - m * 60);
  return s ? `${m}m ${s}s` : `${m}m`;
}

/* Live duration estimate from raw text — mirrors the backend heuristic
 * (words / 2.5 ≈ seconds) so the UI stays in sync without a round-trip. */
function estimateSeconds(text: string): number {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return words / 2.5;
}

function videoStatusOf(issue: UpscIssue | null): VideoStatus {
  const v = (issue?.video_status ?? 'none') as VideoStatus;
  return (['none', 'queued', 'rendering', 'uploading', 'ready', 'error'] as VideoStatus[]).includes(v)
    ? v
    : 'none';
}

/* match the free-text video_progress label to a stage index for the strip */
function activeStageIndex(progress: string | null | undefined): number {
  if (!progress) return -1;
  const p = progress.toLowerCase();
  for (let i = 0; i < VIDEO_STAGES.length; i++) {
    if (p.includes(VIDEO_STAGES[i])) return i;
  }
  return -1;
}

/* ------------------------------------------------------------------ *
 *  ConfirmButton — copied idiom from /admin/upsc/[id]/page.tsx        *
 * ------------------------------------------------------------------ */

function ConfirmButton({
  label,
  confirmLabel,
  onConfirm,
  tone = 'primary',
  disabled = false,
}: {
  label: string;
  confirmLabel: string;
  onConfirm: () => Promise<void> | void;
  tone?: 'primary' | 'danger' | 'ghost';
  disabled?: boolean;
}) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const styleMap: Record<'primary' | 'danger' | 'ghost', React.CSSProperties> = {
    primary: { background: 'var(--c-accent, #2a5b3a)', color: '#fff', border: 'none' },
    danger: { background: '#b91c1c', color: '#fff', border: 'none' },
    ghost: { background: 'transparent', color: 'var(--c-ink-2)', border: '1px solid var(--c-line-2)' },
  };
  return (
    <button
      type="button"
      disabled={disabled || busy}
      onClick={async () => {
        if (!armed) {
          setArmed(true);
          setTimeout(() => setArmed(false), 4000);
          return;
        }
        setBusy(true);
        try {
          await onConfirm();
        } finally {
          setBusy(false);
          setArmed(false);
        }
      }}
      style={{
        padding: '8px 16px',
        fontSize: 13,
        fontWeight: 500,
        borderRadius: 8,
        cursor: disabled || busy ? 'not-allowed' : 'pointer',
        opacity: disabled || busy ? 0.5 : 1,
        ...styleMap[tone],
      }}
    >
      {busy ? 'Working…' : armed ? confirmLabel : label}
    </button>
  );
}

/* a plain (non-confirm) button matching the ghost/primary look */
function Btn({
  children,
  onClick,
  tone = 'ghost',
  disabled = false,
  type = 'button',
  small = false,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  tone?: 'primary' | 'ghost';
  disabled?: boolean;
  type?: 'button' | 'submit';
  small?: boolean;
}) {
  const styleMap: Record<'primary' | 'ghost', React.CSSProperties> = {
    primary: { background: 'var(--c-accent, #2a5b3a)', color: '#fff', border: 'none' },
    ghost: { background: 'transparent', color: 'var(--c-ink-2)', border: '1px solid var(--c-line-2)' },
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: small ? '5px 10px' : '8px 16px',
        fontSize: small ? 12 : 13,
        fontWeight: 500,
        borderRadius: 8,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        ...styleMap[tone],
      }}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ *
 *  Inline error banner                                                *
 * ------------------------------------------------------------------ */

function ErrorBanner({ msg }: { msg: string | null }) {
  if (!msg) return null;
  return (
    <div
      role="alert"
      style={{
        color: '#b91c1c',
        fontSize: 13,
        margin: '10px 0',
        padding: '8px 12px',
        background: '#fef2f2',
        borderRadius: 8,
        border: '1px solid #fecaca',
      }}
    >
      {msg}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Radio pill row                                                     *
 * ------------------------------------------------------------------ */

function RadioRow<T extends string>({
  options,
  value,
  onChange,
  disabled = false,
}: {
  options: Array<{ id: T; label: string; sub?: string }>;
  value: T;
  onChange: (v: T) => void;
  disabled?: boolean;
}) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {options.map((o) => {
        const active = o.id === value;
        return (
          <button
            key={o.id}
            type="button"
            disabled={disabled}
            onClick={() => onChange(o.id)}
            style={{
              textAlign: 'left',
              padding: '8px 12px',
              borderRadius: 10,
              border: active ? '1px solid var(--c-accent, #2a5b3a)' : '1px solid var(--c-line-2)',
              background: active ? 'var(--c-accent-2, #eef5ef)' : 'var(--c-surface-2, #f5f1ea)',
              cursor: disabled ? 'not-allowed' : 'pointer',
              opacity: disabled ? 0.55 : 1,
              minWidth: 120,
            }}
          >
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: active ? 'var(--c-accent-ink, #1d4029)' : 'var(--c-ink)',
              }}
            >
              {o.label}
            </div>
            {o.sub && (
              <div style={{ fontSize: 11, color: 'var(--c-ink-3)', marginTop: 1 }}>{o.sub}</div>
            )}
          </button>
        );
      })}
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        color: 'var(--c-ink-3)',
        fontFamily: 'var(--font-mono)',
        letterSpacing: '.06em',
        marginBottom: 6,
      }}
    >
      {children}
    </div>
  );
}

/* ================================================================== *
 *  PAGE                                                               *
 * ================================================================== */

function IssueCalendar({
  issues,
  selectedId,
  onPick,
}: {
  issues: UpscIssue[];
  selectedId: string;
  onPick: (id: string) => void;
}) {
  const byDate = useMemo(() => {
    const m: Record<string, UpscIssue> = {};
    for (const it of issues) m[it.issue_date.slice(0, 10)] = it;
    return m;
  }, [issues]);

  const [view, setView] = useState(() => {
    const base = issues[0]?.issue_date ? new Date(issues[0].issue_date) : new Date();
    return { y: base.getFullYear(), m: base.getMonth() };
  });

  const first = new Date(view.y, view.m, 1);
  const startOffset = first.getDay();
  const daysInMonth = new Date(view.y, view.m + 1, 0).getDate();
  const monthName = first.toLocaleString('en-US', { month: 'long', year: 'numeric' });

  const cells: (number | null)[] = [];
  for (let i = 0; i < startOffset; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  const key = (d: number) =>
    `${view.y}-${String(view.m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;

  const nav = (label: string, delta: number) => (
    <button
      type="button"
      aria-label={delta < 0 ? 'Previous month' : 'Next month'}
      onClick={() =>
        setView((v) => {
          const nm = v.m + delta;
          return { y: v.y + Math.floor(nm / 12), m: ((nm % 12) + 12) % 12 };
        })
      }
      style={{
        border: '1px solid var(--c-line-2)',
        background: 'transparent',
        color: 'var(--c-ink-2)',
        borderRadius: 8,
        padding: '2px 12px',
        cursor: 'pointer',
        fontSize: 16,
        lineHeight: 1.4,
      }}
    >
      {label}
    </button>
  );

  return (
    <div style={{ maxWidth: 340 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 10,
        }}
      >
        {nav('‹', -1)}
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--c-ink)' }}>{monthName}</div>
        {nav('›', 1)}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 4 }}>
        {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d, i) => (
          <div
            key={i}
            style={{ textAlign: 'center', fontSize: 11, color: 'var(--c-ink-3)', paddingBottom: 2 }}
          >
            {d}
          </div>
        ))}
        {cells.map((d, i) => {
          if (d === null) return <div key={i} />;
          const it = byDate[key(d)];
          const isSel = Boolean(it && it.id === selectedId);
          const hasVid = Boolean(it && it.video_status && it.video_status !== 'none');
          return (
            <button
              key={i}
              type="button"
              disabled={!it}
              onClick={() => it && onPick(it.id)}
              title={
                it
                  ? `${formatDate(it.issue_date)} · ${it.source}${hasVid ? ` · video:${it.video_status}` : ''}`
                  : 'No digest for this date'
              }
              style={{
                position: 'relative',
                aspectRatio: '1 / 1',
                borderRadius: 8,
                fontSize: 13,
                cursor: it ? 'pointer' : 'default',
                border: isSel
                  ? '1px solid var(--c-accent, #2a5b3a)'
                  : it
                    ? '1px solid var(--c-line-2)'
                    : '1px solid transparent',
                background: isSel
                  ? 'var(--c-accent, #2a5b3a)'
                  : it
                    ? 'var(--c-surface-2, #f5f1ea)'
                    : 'transparent',
                color: isSel ? '#fff' : it ? 'var(--c-ink)' : 'var(--c-ink-3)',
                opacity: it ? 1 : 0.45,
                fontWeight: it ? 600 : 400,
              }}
            >
              {d}
              {hasVid && !isSel ? (
                <span
                  style={{
                    position: 'absolute',
                    bottom: 4,
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: 5,
                    height: 5,
                    borderRadius: '50%',
                    background: 'var(--c-accent, #2a5b3a)',
                  }}
                />
              ) : null}
            </button>
          );
        })}
      </div>
      <div style={{ marginTop: 8, fontSize: 11, color: 'var(--c-ink-3)' }}>
        Highlighted dates have an authored digest · dot = video already made
      </div>
    </div>
  );
}

export default function AdminUpscVideoStudioPage() {
  const [issues, setIssues] = useState<UpscIssue[] | null>(null);
  const [selectedId, setSelectedId] = useState<string>('');
  const [issue, setIssue] = useState<(UpscIssue & { markdown: string | null }) | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  /* ---- variant config (the four controls) ---- */
  const [config, setConfig] = useState<VideoConfig>(DEFAULT_CONFIG);
  const [sampleMode, setSampleMode] = useState(false);
  const [thumbErr, setThumbErr] = useState(false);
  useEffect(() => {
    setThumbErr(false);
  }, [selectedId]);
  const [coverSlide, setCoverSlide] = useState(true);
  const [introOutro, setIntroOutro] = useState(true);

  /* ---- voice ---- */
  const [voices, setVoices] = useState<VoiceOption[] | null>(null);
  const [voicesError, setVoicesError] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const previewUrlRef = useRef<string | null>(null);

  /* ---- script ---- */
  const [sections, setSections] = useState<NarrationSection[] | null>(null);
  const [scriptBusy, setScriptBusy] = useState(false);
  const [scriptError, setScriptError] = useState<string | null>(null);
  const [scriptConfirmed, setScriptConfirmed] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [regenIdx, setRegenIdx] = useState<number | null>(null);
  const [scriptProgress, setScriptProgress] = useState(0);
  /* monotonic token: switching issues / unmount bumps it to cancel any
   * in-flight script poll (the running loop sees its token go stale). */
  const scriptPollRef = useRef(0);

  /* ---- video / publish ---- */
  const [makeError, setMakeError] = useState<string | null>(null);
  const [ytTitle, setYtTitle] = useState('');
  const [ytDesc, setYtDesc] = useState('');
  const [ytTags, setYtTags] = useState('');
  const [ytError, setYtError] = useState<string | null>(null);

  /* ---- defaults ---- */
  const [defaultsOpen, setDefaultsOpen] = useState(false);
  const [defaults, setDefaults] = useState<VideoDefaults | null>(null);
  const [defaultsError, setDefaultsError] = useState<string | null>(null);
  const [defaultsSaved, setDefaultsSaved] = useState(false);

  /* ============================================================== *
   *  Load + poll issues list                                       *
   * ============================================================== */
  const refreshList = useCallback(() => {
    adminApi
      .listUpscIssues(50, 0)
      .then((r) => setIssues(r.issues))
      .catch((e) => setListError(String(e instanceof Error ? e.message : e)));
  }, []);

  useEffect(() => {
    refreshList();
    const t = setInterval(refreshList, 5000);
    return () => clearInterval(t);
  }, [refreshList]);

  /* ============================================================== *
   *  Upload a newspaper PDF -> digest pipeline                      *
   * ============================================================== */
  const [upFile, setUpFile] = useState<File | null>(null);
  const [upDate, setUpDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [upSource, setUpSource] = useState('Indian Express');
  const [upTitle, setUpTitle] = useState('');
  const [upStyle, setUpStyle] = useState<UpscStyle>('dense_tight');
  const [uploading, setUploading] = useState(false);
  const [upErr, setUpErr] = useState<string | null>(null);
  const upFileRef = useRef<HTMLInputElement>(null);

  const submitUpload = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!upFile) {
        setUpErr('Pick a PDF file first.');
        return;
      }
      setUploading(true);
      setUpErr(null);
      try {
        const fd = new FormData();
        fd.append('pdf', upFile);
        fd.append('issue_date', upDate);
        fd.append('source', upSource);
        if (upTitle) fd.append('title', upTitle);
        fd.append('style', upStyle);
        await adminApi.uploadUpscIssue(fd);
        setUpFile(null);
        setUpTitle('');
        if (upFileRef.current) upFileRef.current.value = '';
        refreshList();
      } catch (e: unknown) {
        setUpErr(String(e instanceof Error ? e.message : e));
      } finally {
        setUploading(false);
      }
    },
    [upFile, upDate, upSource, upTitle, upStyle, refreshList],
  );

  const processing = useMemo(
    () =>
      (issues ?? []).filter((i) =>
        ['uploaded', 'extracting', 'classifying', 'authoring', 'rendering'].includes(i.status),
      ),
    [issues],
  );

  /* Load defaults once. */
  useEffect(() => {
    adminApi
      .getVideoDefaults()
      .then((d) => {
        setDefaults(d);
        // Seed the working config from defaults (voice filled after voices load).
        setConfig((c) => ({
          ...c,
          engine: d.engine,
          lang: d.lang,
          slide_style: d.slide_style,
          theme: d.theme,
          privacy: d.privacy,
        }));
      })
      .catch((e) => setDefaultsError(String(e instanceof Error ? e.message : e)));
  }, []);

  /* ============================================================== *
   *  Load the selected issue (and its script) + poll while busy    *
   * ============================================================== */
  const loadIssue = useCallback(() => {
    if (!selectedId) return;
    adminApi
      .getUpscIssue(selectedId)
      .then((r) => {
        setIssue(r);
        // hydrate script + confirmed from persisted narration_script
        if (r.narration_script) {
          try {
            const parsed = JSON.parse(r.narration_script) as NarrationSection[];
            if (Array.isArray(parsed)) {
              setSections((prev) => (dirty ? prev : parsed));
            }
          } catch {
            /* ignore malformed persisted script */
          }
        }
        if (!dirty) setScriptConfirmed(Boolean(r.script_confirmed));
        // hydrate any saved video_config
        if (r.video_config) {
          try {
            const vc = JSON.parse(r.video_config) as Partial<VideoConfig>;
            setConfig((c) => ({ ...c, ...vc }));
          } catch {
            /* ignore */
          }
        }
      })
      .catch((e) => setListError(String(e instanceof Error ? e.message : e)));
  }, [selectedId, dirty]);

  useEffect(() => {
    // reset per-issue UI state when the picker changes
    setIssue(null);
    setSections(null);
    setScriptConfirmed(false);
    setDirty(false);
    setScriptError(null);
    setMakeError(null);
    setYtError(null);
    if (selectedId) loadIssue();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const vStatus = videoStatusOf(issue);
  const videoBusy = VIDEO_IN_FLIGHT.includes(vStatus);

  /* 5 s polling — list always, selected issue while a video job runs. */
  useEffect(() => {
    const t = setInterval(() => {
      refreshList();
      if (selectedId && videoBusy) loadIssue();
    }, 5000);
    return () => clearInterval(t);
  }, [refreshList, loadIssue, selectedId, videoBusy]);

  /* ============================================================== *
   *  Voices — reload whenever engine/lang changes                  *
   * ============================================================== */
  useEffect(() => {
    let cancelled = false;
    setVoices(null);
    setVoicesError(null);
    adminApi
      .getVoices(config.engine, config.lang)
      .then((vs) => {
        if (cancelled) return;
        setVoices(vs);
        // pick default voice if current selection isn't valid for this engine/lang
        setConfig((c) => {
          const stillValid = vs.some((v) => v.id === c.voice);
          if (stillValid) return c;
          const def = vs.find((v) => v.is_default) ?? vs[0];
          return { ...c, voice: def ? def.id : '' };
        });
      })
      .catch((e) => {
        if (!cancelled) setVoicesError(String(e instanceof Error ? e.message : e));
      });
    return () => {
      cancelled = true;
    };
  }, [config.engine, config.lang]);

  /* clean up preview object URL on unmount */
  useEffect(() => {
    return () => {
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    };
  }, []);

  /* ============================================================== *
   *  Handlers                                                      *
   * ============================================================== */

  const setCfg = useCallback(<K extends keyof VideoConfig>(key: K, val: VideoConfig[K]) => {
    setConfig((c) => ({ ...c, [key]: val }));
  }, []);

  const onPreviewVoice = useCallback(async () => {
    if (!config.voice) return;
    setPreviewBusy(true);
    setPreviewError(null);
    try {
      const blob = await adminApi.previewVoice({
        engine: config.engine,
        voice: config.voice,
        lang: config.lang,
        text: PREVIEW_SAMPLE[config.lang],
      });
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
      const url = URL.createObjectURL(blob);
      previewUrlRef.current = url;
      if (audioRef.current) {
        audioRef.current.src = url;
        await audioRef.current.play().catch(() => {});
      }
    } catch (e) {
      setPreviewError(String(e instanceof Error ? e.message : e));
    } finally {
      setPreviewBusy(false);
    }
  }, [config.engine, config.voice, config.lang]);

  /* Switching issues (or unmounting) cancels any in-flight script poll: the
   * running loop sees its token go stale and bails with '__cancelled__'. */
  useEffect(() => () => {
    scriptPollRef.current += 1;
  }, [selectedId]);

  /* Kick an async script job and poll it to completion. Shared by "Generate",
   * "Regenerate all" and per-section regen. Polls every 2s; gives up after
   * 5 min. Throws '__cancelled__' if superseded (issue switch / unmount), or
   * Error(message) on failed/timeout. Resolves with the finished sections. */
  const runScriptJob = useCallback(
    async (id: string, lang: 'hi' | 'en'): Promise<NarrationSection[]> => {
      const token = (scriptPollRef.current += 1); // invalidate any prior poll
      setScriptProgress(0);
      const { job_id } = await adminApi.generateScript(id, lang);
      const deadline = Date.now() + 5 * 60 * 1000; // 5-minute cap
      for (;;) {
        if (scriptPollRef.current !== token) throw new Error('__cancelled__');
        const job = await adminApi.getScriptJob(job_id);
        // Re-check AFTER the await: the issue may have switched (or the component
        // unmounted) WHILE this GET was in flight. Without this, a poll that
        // resolves 'done' on the same tick as an issue-switch would clobber the
        // newly-selected issue's sections (and write a stale progress %). This
        // single guard fixes the stale-clobber, stale-progress and
        // setState-after-unmount races in one place.
        if (scriptPollRef.current !== token) throw new Error('__cancelled__');
        setScriptProgress(job.progress);
        if (job.status === 'done') {
          const secs = job.result?.sections;
          if (!secs || secs.length === 0) {
            throw new Error('Generation finished but returned no script.');
          }
          return secs;
        }
        if (job.status === 'failed') {
          throw new Error(job.error || 'Script generation failed.');
        }
        if (Date.now() >= deadline) {
          throw new Error('Generation timed out; check back later. You can retry.');
        }
        await new Promise<void>((res) => setTimeout(res, 2000));
      }
    },
    [],
  );

  const onGenerateScript = useCallback(async () => {
    if (!selectedId) return;
    setScriptBusy(true);
    setScriptError(null);
    try {
      const secs = await runScriptJob(selectedId, config.lang);
      setSections(secs);
      setScriptConfirmed(false);
      setDirty(true);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg !== '__cancelled__') setScriptError(msg);
    } finally {
      setScriptBusy(false);
    }
  }, [selectedId, config.lang, runScriptJob]);

  const onEditSection = useCallback((idx: number, text: string) => {
    setSections((prev) => {
      if (!prev) return prev;
      const next = [...prev];
      next[idx] = { ...next[idx], text, est_seconds: estimateSeconds(text) };
      return next;
    });
    setDirty(true);
    setScriptConfirmed(false);
  }, []);

  /* Regenerate a single section: re-run the full generator, swap in just
   * that section's fresh text. (No per-section endpoint in the contract.) */
  const onRegenSection = useCallback(
    async (idx: number) => {
      if (!selectedId || !sections) return;
      setRegenIdx(idx);
      setScriptError(null);
      try {
        const secs = await runScriptJob(selectedId, config.lang);
        const fresh = secs.find((s) => s.section_id === sections[idx].section_id);
        if (fresh) {
          setSections((prev) => {
            if (!prev) return prev;
            const next = [...prev];
            next[idx] = fresh;
            return next;
          });
          setDirty(true);
          setScriptConfirmed(false);
        } else {
          setScriptError('Could not find a matching section to regenerate.');
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (msg !== '__cancelled__') setScriptError(msg);
      } finally {
        setRegenIdx(null);
      }
    },
    [selectedId, sections, config.lang, runScriptJob],
  );

  const onSaveScript = useCallback(
    async (confirmed: boolean) => {
      if (!selectedId || !sections) return;
      setScriptError(null);
      try {
        await adminApi.saveScript(selectedId, sections, confirmed);
        setScriptConfirmed(confirmed);
        setDirty(false);
      } catch (e) {
        setScriptError(String(e instanceof Error ? e.message : e));
        throw e;
      }
    },
    [selectedId, sections],
  );

  const onMakeVideo = useCallback(async () => {
    if (!selectedId) return;
    setMakeError(null);
    try {
      const updated = await adminApi.makeVideo(selectedId, { ...config, sample: sampleMode });
      setIssue((prev) => (prev ? { ...prev, ...updated } : prev));
      // force a fresh load so polling kicks in immediately
      loadIssue();
    } catch (e) {
      setMakeError(String(e instanceof Error ? e.message : e));
      throw e;
    }
  }, [selectedId, config, sampleMode, loadIssue]);

  const onPublishYoutube = useCallback(async () => {
    if (!selectedId) return;
    setYtError(null);
    try {
      const r = await adminApi.publishYoutube(selectedId, {
        title: ytTitle,
        description: ytDesc,
        tags: ytTags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
        privacy: config.privacy,
      });
      setIssue((prev) => (prev ? { ...prev, youtube_url: r.youtube_url } : prev));
      loadIssue();
    } catch (e) {
      setYtError(String(e instanceof Error ? e.message : e));
      throw e;
    }
  }, [selectedId, ytTitle, ytDesc, ytTags, config.privacy, loadIssue]);

  const onSaveDefaults = useCallback(async () => {
    if (!defaults) return;
    setDefaultsError(null);
    setDefaultsSaved(false);
    try {
      await adminApi.putVideoDefaults(defaults);
      setDefaultsSaved(true);
      setTimeout(() => setDefaultsSaved(false), 2500);
    } catch (e) {
      setDefaultsError(String(e instanceof Error ? e.message : e));
    }
  }, [defaults]);

  /* ============================================================== *
   *  Derived values                                                *
   * ============================================================== */

  const totalSeconds = useMemo(
    () => (sections ? sections.reduce((a, s) => a + (s.est_seconds || 0), 0) : 0),
    [sections],
  );

  const geminiBillingActive =
    (issue as unknown as { gemini_billing_active?: boolean } | null)?.gemini_billing_active ?? true;

  /* issues that have an authored digest are eligible for video */
  const eligibleIssues = useMemo(
    () => issues?.filter((i) => i.status === 'preview' || i.status === 'published') ?? [],
    [issues],
  );

  const stageIdx = activeStageIndex(issue?.video_progress);
  const hasVideo = vStatus === 'ready' || Boolean(issue?.video_path);

  /* ============================================================== *
   *  Render                                                        *
   * ============================================================== */

  return (
    <AdminShell>
      <PageHeader
        eyebrow="UPSC CHEETSHEET"
        title="🎬 Video Studio"
        right={
          <button
            type="button"
            onClick={() => setDefaultsOpen((o) => !o)}
            style={{
              padding: '7px 14px',
              fontSize: 13,
              background: 'transparent',
              color: 'var(--c-ink-2)',
              border: '1px solid var(--c-line-2)',
              borderRadius: 8,
              cursor: 'pointer',
            }}
          >
            Defaults {defaultsOpen ? '▴' : '▾'}
          </button>
        }
      />

      {/* hidden audio element for voice preview */}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={audioRef} style={{ display: 'none' }} />

      {/* ---------------- Defaults panel (collapsible) ---------------- */}
      {defaultsOpen && (
        <Section
          title="Defaults"
          description="Persisted server-side. New issues pre-fill from these; auto-generate uses them unattended (still behind the QC gate)."
          right={
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {defaultsSaved && <Tag tone="mint">saved</Tag>}
              <ConfirmButton
                label="Save defaults"
                confirmLabel="Click again to save"
                onConfirm={onSaveDefaults}
                disabled={!defaults}
              />
            </div>
          }
        >
          <ErrorBanner msg={defaultsError} />
          {!defaults && !defaultsError && (
            <div style={{ color: 'var(--c-ink-3)' }}>Loading defaults…</div>
          )}
          {defaults && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
              <div>
                <FieldLabel>DEFAULT ENGINE</FieldLabel>
                <RadioRow
                  options={ENGINES}
                  value={defaults.engine}
                  onChange={(v) => setDefaults({ ...defaults, engine: v })}
                />
                <div style={{ height: 14 }} />
                <FieldLabel>DEFAULT LANGUAGE</FieldLabel>
                <RadioRow
                  options={LANGS}
                  value={defaults.lang}
                  onChange={(v) => setDefaults({ ...defaults, lang: v })}
                />
                <div style={{ height: 14 }} />
                <FieldLabel>DEFAULT SLIDE STYLE</FieldLabel>
                <RadioRow
                  options={SLIDE_STYLES.map((s) => ({ id: s.id, label: s.label }))}
                  value={defaults.slide_style}
                  onChange={(v) => setDefaults({ ...defaults, slide_style: v })}
                />
              </div>
              <div>
                <FieldLabel>DEFAULT THEME</FieldLabel>
                <select
                  value={defaults.theme}
                  onChange={(e) => setDefaults({ ...defaults, theme: e.target.value })}
                  style={selectStyle}
                >
                  {THEMES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                <div style={{ height: 14 }} />
                <FieldLabel>DEFAULT PRIVACY</FieldLabel>
                <RadioRow
                  options={PRIVACIES}
                  value={defaults.privacy}
                  onChange={(v) => setDefaults({ ...defaults, privacy: v })}
                />
                <div style={{ height: 16 }} />
                <Toggle
                  label="Auto-publish to YouTube"
                  hint="Upload the rendered video without a manual click (QC gate still applies)."
                  checked={defaults.auto_publish}
                  onChange={(v) => setDefaults({ ...defaults, auto_publish: v })}
                />
                <Toggle
                  label="Auto-generate on upload"
                  hint="Produce the video unattended right after a digest is authored."
                  checked={defaults.auto_generate_on_upload}
                  onChange={(v) => setDefaults({ ...defaults, auto_generate_on_upload: v })}
                />
              </div>
              <div style={{ gridColumn: '1 / -1' }}>
                <Input
                  label="YOUTUBE TITLE TEMPLATE"
                  value={defaults.title_template}
                  onChange={(e) => setDefaults({ ...defaults, title_template: e.target.value })}
                  hint="Use placeholders like {date} / {source}."
                />
                <Textarea
                  label="YOUTUBE DESCRIPTION TEMPLATE"
                  value={defaults.description_template}
                  onChange={(e) =>
                    setDefaults({ ...defaults, description_template: e.target.value })
                  }
                  style={{ minHeight: 90 }}
                />
              </div>
            </div>
          )}
        </Section>
      )}

      {/* ---------------- Upload newspaper (digest pipeline) ---------------- */}
      <Section
        title="Upload newspaper"
        description="Drop today's e-paper PDF. The digest pipeline extracts → classifies → authors → renders (~5–10 min); the date then lights up below, ready to videofy."
      >
        <form onSubmit={submitUpload}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Input
              label="ISSUE DATE"
              type="date"
              value={upDate}
              onChange={(e) => setUpDate(e.target.value)}
              required
            />
            <Input
              label="SOURCE NEWSPAPER"
              type="text"
              value={upSource}
              onChange={(e) => setUpSource(e.target.value)}
              placeholder="Indian Express"
              required
            />
          </div>
          <Input
            label="TITLE (OPTIONAL)"
            type="text"
            value={upTitle}
            onChange={(e) => setUpTitle(e.target.value)}
            placeholder="Defaults to 'UPSC Cheetsheet - <date>'"
          />
          <Select
            label="RENDERER STYLE"
            value={upStyle}
            onChange={(e) => setUpStyle(e.target.value as UpscStyle)}
          >
            <option value="dense_tight">Dense Tight (default)</option>
            <option value="dense">Dense</option>
            <option value="academic">Academic</option>
            <option value="coaching">Coaching</option>
            <option value="magazine">Magazine</option>
          </Select>
          <label style={{ display: 'block', marginBottom: 12 }}>
            <div
              style={{
                fontSize: 11,
                color: 'var(--c-ink-3)',
                letterSpacing: '.06em',
                marginBottom: 5,
              }}
            >
              NEWSPAPER PDF
            </div>
            <input
              ref={upFileRef}
              type="file"
              accept="application/pdf"
              onChange={(e) => setUpFile(e.target.files?.[0] ?? null)}
              required
              style={{ width: '100%', fontSize: 13 }}
            />
          </label>
          {upErr && (
            <div
              style={{
                color: '#b91c1c',
                fontSize: 13,
                marginBottom: 10,
                padding: '8px 12px',
                background: '#fef2f2',
                borderRadius: 8,
                border: '1px solid #fecaca',
              }}
            >
              {upErr}
            </div>
          )}
          <button
            type="submit"
            disabled={uploading || !upFile}
            style={{
              background: uploading || !upFile ? 'var(--c-line-2)' : 'var(--c-accent, #2a5b3a)',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              padding: '9px 18px',
              fontSize: 14,
              fontWeight: 600,
              cursor: uploading || !upFile ? 'default' : 'pointer',
            }}
          >
            {uploading ? 'Uploading…' : 'Upload & process'}
          </button>
        </form>
        {processing.length > 0 && (
          <div style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--c-line-2)' }}>
            <div style={{ fontSize: 12, color: 'var(--c-ink-3)', marginBottom: 8 }}>
              Processing (auto-refreshing)
            </div>
            {processing.map((i) => (
              <div
                key={i.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '6px 0',
                }}
              >
                <span style={{ fontSize: 13, color: 'var(--c-ink)' }}>
                  {formatDate(i.issue_date)} · {i.source}
                </span>
                <Tag tone="accent">{STATUS_LABEL[i.status]}</Tag>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* ---------------- Issue picker ---------------- */}
      <Section
        title="Pick an issue"
        description="Choose an authored digest to turn into a narrated video."
        right={
          issue ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Tag tone={STATUS_TONE[issue.status]}>{STATUS_LABEL[issue.status]}</Tag>
              <Tag tone={VIDEO_STATUS_TONE[vStatus]}>video: {VIDEO_STATUS_LABEL[vStatus]}</Tag>
            </div>
          ) : null
        }
      >
        <ErrorBanner msg={listError} />
        {issues === null && !listError && (
          <div style={{ color: 'var(--c-ink-3)' }}>Loading issues…</div>
        )}
        {issues !== null && eligibleIssues.length === 0 && (
          <div style={{ color: 'var(--c-ink-3)' }}>
            No authored digests yet.{' '}
            <Link href="/admin/upsc" style={{ color: 'var(--c-accent, #2a5b3a)' }}>
              Upload one first →
            </Link>
          </div>
        )}
        {eligibleIssues.length > 0 && (
          <IssueCalendar
            issues={eligibleIssues}
            selectedId={selectedId}
            onPick={setSelectedId}
          />
        )}
      </Section>

      {selectedId && issue && (
        <>
          {/* ---------------- 1. SCRIPT ---------------- */}
          <Section
            title="1 · Script (confirm / edit)"
            description="Spoken rewrite of the authored digest. Edit per-section, then confirm — TTS won't run until confirmed."
            right={
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                {sections && (
                  <span style={{ fontSize: 12, color: 'var(--c-ink-3)' }}>
                    ~{fmtSeconds(totalSeconds)} · {sections.length} sections
                  </span>
                )}
                {scriptConfirmed && !dirty && <Tag tone="mint">confirmed</Tag>}
                {dirty && <Tag tone="gold">unsaved</Tag>}
              </div>
            }
          >
            <ErrorBanner msg={scriptError} />
            {!sections && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <ConfirmButton
                  label="Generate script"
                  confirmLabel="Click again to generate"
                  onConfirm={onGenerateScript}
                  disabled={scriptBusy}
                />
                {scriptBusy && (
                  <span
                    role="status"
                    aria-live="polite"
                    aria-atomic="true"
                    style={{ fontSize: 13, color: 'var(--c-ink-3)' }}
                  >
                    {scriptProgress >= 50
                      ? 'Rewriting the digest as spoken narration…'
                      : 'Queued…'}{' '}
                    ({scriptProgress}%) · runs in the background (~1 min)
                  </span>
                )}
              </div>
            )}

            {sections && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {sections.map((s, idx) => (
                  <div
                    key={s.section_id}
                    style={{
                      border: '1px solid var(--c-line)',
                      borderRadius: 10,
                      padding: 12,
                      background: 'var(--c-surface-2, #f5f1ea)',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: 6,
                      }}
                    >
                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--c-ink)' }}>
                        §{idx + 1} · {s.label}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: 12, color: 'var(--c-ink-3)' }}>
                          ~{fmtSeconds(s.est_seconds || estimateSeconds(s.text))}
                        </span>
                        <Btn
                          small
                          tone="ghost"
                          onClick={() => onRegenSection(idx)}
                          disabled={regenIdx !== null || scriptBusy}
                        >
                          {regenIdx === idx ? '↻ …' : '↻ Regen'}
                        </Btn>
                      </div>
                    </div>
                    <textarea
                      value={s.text}
                      onChange={(e) => onEditSection(idx, e.target.value)}
                      style={{
                        width: '100%',
                        minHeight: 80,
                        padding: '9px 12px',
                        borderRadius: 8,
                        border: '1px solid var(--c-line-2)',
                        background: 'var(--c-surface)',
                        fontSize: 13.5,
                        outline: 'none',
                        fontFamily: 'inherit',
                        resize: 'vertical',
                        lineHeight: 1.5,
                      }}
                    />
                  </div>
                ))}

                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: 12,
                  }}
                >
                  <Btn
                    onClick={onGenerateScript}
                    disabled={scriptBusy || regenIdx !== null}
                    tone="ghost"
                  >
                    {scriptBusy ? 'Regenerating…' : '↻ Regenerate all'}
                  </Btn>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <Btn onClick={() => onSaveScript(false)} tone="ghost">
                      Save draft
                    </Btn>
                    <ConfirmButton
                      label="✓ Confirm script"
                      confirmLabel="Click again — locks for TTS"
                      onConfirm={() => onSaveScript(true)}
                    />
                  </div>
                </div>
              </div>
            )}
          </Section>

          {/* ---------------- SLIDES + VOICE (two-up grid) ---------------- */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))',
              gap: 16,
            }}
          >
            {/* ---- 2. SLIDES ---- */}
            <Section title="2 · Slides" description="Visual style, accent theme and cover/intro slides.">
              <FieldLabel>STYLE</FieldLabel>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {SLIDE_STYLES.map((s) => {
                  const active = config.slide_style === s.id;
                  return (
                    <button
                      key={s.id}
                      type="button"
                      disabled={videoBusy}
                      onClick={() => setCfg('slide_style', s.id)}
                      style={{
                        textAlign: 'left',
                        padding: '10px 12px',
                        borderRadius: 10,
                        border: active
                          ? '1px solid var(--c-accent, #2a5b3a)'
                          : '1px solid var(--c-line-2)',
                        background: active
                          ? 'var(--c-accent-2, #eef5ef)'
                          : 'var(--c-surface-2, #f5f1ea)',
                        cursor: videoBusy ? 'not-allowed' : 'pointer',
                        opacity: videoBusy ? 0.6 : 1,
                      }}
                    >
                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--c-ink)' }}>
                        {active ? '◉ ' : '○ '}
                        {s.label}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--c-ink-3)', marginTop: 1 }}>
                        {s.sub}
                      </div>
                    </button>
                  );
                })}
              </div>

              {issue?.has_cover_thumb && (
                <div style={{ marginTop: 12 }}>
                  <FieldLabel>PREVIEW</FieldLabel>
                  {thumbErr ? (
                    <div
                      style={{
                        fontSize: 12,
                        color: 'var(--c-ink-3)',
                        padding: '14px 12px',
                        background: 'var(--c-surface-2, #f5f1ea)',
                        borderRadius: 10,
                        border: '1px dashed var(--c-line-2)',
                        maxWidth: 320,
                      }}
                    >
                      Preview image isn&apos;t on disk for this issue (digest files were
                      cleaned). The video still renders fine from the live digest — or
                      re-render the issue to regenerate the cover.
                    </div>
                  ) : (
                    <img
                      key={issue.id}
                      src={adminApi.thumbUrl(issue.id)}
                      alt="slide preview"
                      onError={() => setThumbErr(true)}
                      style={{
                        width: '100%',
                        maxWidth: 320,
                        borderRadius: 10,
                        border: '1px solid var(--c-line-2)',
                        display: 'block',
                      }}
                    />
                  )}
                  <div style={{ fontSize: 11, color: 'var(--c-ink-3)', marginTop: 4 }}>
                    {config.slide_style === 'clean'
                      ? 'Source digest. Your video uses the branded 16:9 deck (rendered from this content).'
                      : config.slide_style === 'animated'
                        ? 'First digest page. (Animated coming soon — renders as digest pages for now.)'
                        : 'First digest page — slides letterbox this to 1920×1080.'}
                  </div>
                </div>
              )}

              <div style={{ height: 14 }} />
              <FieldLabel>THEME / ACCENT</FieldLabel>
              <select
                value={config.theme}
                onChange={(e) => setCfg('theme', e.target.value)}
                disabled={videoBusy}
                style={selectStyle}
              >
                {THEMES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>

              <div style={{ height: 12 }} />
              <Toggle label="Cover slide" checked={coverSlide} onChange={setCoverSlide} />
              <Toggle label="Intro / outro slides" checked={introOutro} onChange={setIntroOutro} />
            </Section>
            {/* ---- 3. VOICE ---- */}
            <Section title="3 · Voice" description="Engine, language and the narration voice.">
              <FieldLabel>ENGINE</FieldLabel>
              <RadioRow
                options={ENGINES}
                value={config.engine}
                onChange={(v) => setCfg('engine', v)}
                disabled={videoBusy}
              />
              {config.engine === 'gemini' && !geminiBillingActive && (
                <div
                  style={{
                    marginTop: 8,
                    fontSize: 11.5,
                    color: '#92400e',
                    background: '#fef3c7',
                    border: '1px solid #fde68a',
                    borderRadius: 8,
                    padding: '6px 10px',
                  }}
                >
                  Gemini credits pending → falls back to Chirp3-HD at render time.
                </div>
              )}

              <div style={{ height: 14 }} />
              <FieldLabel>LANGUAGE</FieldLabel>
              <RadioRow
                options={LANGS}
                value={config.lang}
                onChange={(v) => setCfg('lang', v)}
                disabled={videoBusy}
              />

              <div style={{ height: 14 }} />
              <FieldLabel>VOICE</FieldLabel>
              <ErrorBanner msg={voicesError} />
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <select
                  value={config.voice}
                  onChange={(e) => setCfg('voice', e.target.value)}
                  disabled={videoBusy || !voices || voices.length === 0}
                  style={{ ...selectStyle, flex: 1 }}
                >
                  {voices === null && <option>Loading…</option>}
                  {voices &&
                    voices.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.label}
                        {v.is_default ? ' (default)' : ''}
                      </option>
                    ))}
                </select>
                <Btn
                  onClick={onPreviewVoice}
                  disabled={previewBusy || !config.voice}
                  tone="ghost"
                >
                  {previewBusy ? '…' : '▶ Preview'}
                </Btn>
              </div>
              <ErrorBanner msg={previewError} />
            </Section>

          </div>

          {/* ---------------- Generate video ---------------- */}
          <Section
            title="4 · Generate video"
            description="Renders slides, synthesizes the voiceover, stitches the MP4, then (optionally) uploads."
            right={
              <ConfirmButton
                label="🎥 Generate video"
                confirmLabel="Click again to render"
                onConfirm={onMakeVideo}
                disabled={!scriptConfirmed || dirty || videoBusy || !config.voice}
              />
            }
          >
            <ErrorBanner msg={makeError} />
            {(!scriptConfirmed || dirty) && (
              <div style={{ fontSize: 13, color: 'var(--c-ink-3)', marginBottom: 12 }}>
                Confirm the script above before rendering.
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
              {[
                { id: false, label: 'Full video', sub: 'All sections (~10–18 min)' },
                { id: true, label: 'Sample', sub: 'Intro + first story (~1 min)' },
              ].map((m) => {
                const active = sampleMode === m.id;
                return (
                  <button
                    key={String(m.id)}
                    type="button"
                    disabled={videoBusy}
                    onClick={() => setSampleMode(m.id)}
                    style={{
                      flex: 1,
                      textAlign: 'left',
                      padding: '9px 12px',
                      borderRadius: 10,
                      border: active
                        ? '1px solid var(--c-accent, #2a5b3a)'
                        : '1px solid var(--c-line-2)',
                      background: active
                        ? 'var(--c-accent-2, #eef5ef)'
                        : 'var(--c-surface-2, #f5f1ea)',
                      cursor: videoBusy ? 'not-allowed' : 'pointer',
                      opacity: videoBusy ? 0.6 : 1,
                    }}
                  >
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--c-ink)' }}>
                      {active ? '◉ ' : '○ '}
                      {m.label}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--c-ink-3)', marginTop: 1 }}>
                      {m.sub}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* per-stage progress strip */}
            <div style={{ display: 'flex', gap: 8 }}>
              {VIDEO_STAGES.map((stage, i) => {
                const done =
                  vStatus === 'ready' ||
                  (stageIdx >= 0 && i < stageIdx) ||
                  (stage === 'upload' && hasVideo && vStatus !== 'uploading');
                const current = i === stageIdx && videoBusy;
                return (
                  <div key={stage} style={{ flex: 1 }}>
                    <div
                      style={{
                        height: 6,
                        borderRadius: 3,
                        background: done
                          ? 'var(--c-accent, #2a5b3a)'
                          : current
                            ? 'var(--c-gold, #b8860b)'
                            : 'var(--c-line-2, #e5e1d7)',
                        transition: 'background .3s',
                      }}
                    />
                    <div
                      style={{
                        fontSize: 11,
                        marginTop: 4,
                        textAlign: 'center',
                        color: current ? 'var(--c-ink)' : 'var(--c-ink-3)',
                        fontWeight: current ? 600 : 400,
                      }}
                    >
                      {VIDEO_STAGE_LABEL[stage]}
                      {current && ' …'}
                    </div>
                  </div>
                );
              })}
            </div>

            {issue.video_progress && (
              <div style={{ marginTop: 10, fontSize: 12.5, color: 'var(--c-ink-2)' }}>
                Stage: <strong>{issue.video_progress}</strong>
              </div>
            )}
            {vStatus === 'error' && (
              <ErrorBanner msg={issue.error_message || 'Video render failed. See logs.'} />
            )}
          </Section>

          {/* ---------------- Result + YouTube ---------------- */}
          {hasVideo && (
            <Section
              title="Result"
              description="Preview the rendered MP4, then publish to YouTube. QC gate is enforced server-side before any public publish."
            >
              {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
              <video
                src={adminApi.videoUrl(selectedId)}
                controls
                style={{
                  width: '100%',
                  maxHeight: 460,
                  borderRadius: 10,
                  background: '#000',
                  border: '1px solid var(--c-line)',
                }}
              />

              {issue.youtube_url ? (
                <div
                  style={{
                    marginTop: 14,
                    padding: '10px 14px',
                    background: 'var(--c-mint-bg, #d1fae5)',
                    borderRadius: 8,
                    fontSize: 13,
                  }}
                >
                  Published:{' '}
                  <a
                    href={issue.youtube_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: 'var(--c-accent, #2a5b3a)', fontWeight: 600 }}
                  >
                    {issue.youtube_url}
                  </a>
                </div>
              ) : (
                <div style={{ marginTop: 16 }}>
                  <ErrorBanner msg={ytError} />
                  <Input
                    label="YOUTUBE TITLE"
                    value={ytTitle}
                    onChange={(e) => setYtTitle(e.target.value)}
                    placeholder={`UPSC Daily — ${formatDate(issue.issue_date)} · ${issue.source}`}
                  />
                  <Textarea
                    label="DESCRIPTION"
                    value={ytDesc}
                    onChange={(e) => setYtDesc(e.target.value)}
                    style={{ minHeight: 100 }}
                  />
                  <Input
                    label="TAGS (comma-separated)"
                    value={ytTags}
                    onChange={(e) => setYtTags(e.target.value)}
                    placeholder="UPSC, current affairs, daily digest"
                  />
                  <FieldLabel>PRIVACY</FieldLabel>
                  <RadioRow
                    options={PRIVACIES}
                    value={config.privacy}
                    onChange={(v) => setCfg('privacy', v)}
                  />
                  <div style={{ marginTop: 14 }}>
                    <ConfirmButton
                      label="Publish to YouTube"
                      confirmLabel={
                        config.privacy === 'public'
                          ? 'Click again — goes PUBLIC'
                          : 'Click again to upload'
                      }
                      onConfirm={onPublishYoutube}
                      disabled={videoBusy || !ytTitle.trim()}
                    />
                  </div>
                </div>
              )}
            </Section>
          )}
        </>
      )}

      {/* ---------------- History ---------------- */}
      <Section title="History" description="Issues with video activity. Newest first.">
        {issues && issues.filter((i) => i.video_status && i.video_status !== 'none').length === 0 && (
          <div style={{ color: 'var(--c-ink-3)' }}>No videos generated yet.</div>
        )}
        {issues && issues.filter((i) => i.video_status && i.video_status !== 'none').length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '150px 1fr 120px 90px 110px',
                gap: 12,
                padding: '8px 12px',
                fontSize: 11,
                fontFamily: 'var(--font-mono)',
                color: 'var(--c-ink-3)',
                letterSpacing: '0.06em',
                borderBottom: '1px solid var(--c-line)',
              }}
            >
              <div>DATE</div>
              <div>SOURCE</div>
              <div>VIDEO STATUS</div>
              <div>OPEN</div>
              <div>YOUTUBE</div>
            </div>
            {issues
              .filter((i) => i.video_status && i.video_status !== 'none')
              .map((i) => {
                const vs = (i.video_status ?? 'none') as VideoStatus;
                return (
                  <div
                    key={i.id}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '150px 1fr 120px 90px 110px',
                      gap: 12,
                      padding: '10px 12px',
                      alignItems: 'center',
                      borderBottom: '1px solid var(--c-line)',
                      fontSize: 13,
                    }}
                  >
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                      {formatDate(i.issue_date)}
                    </div>
                    <div>{i.source}</div>
                    <div>
                      <Tag tone={VIDEO_STATUS_TONE[vs] ?? 'neutral'}>
                        {VIDEO_STATUS_LABEL[vs] ?? vs}
                      </Tag>
                    </div>
                    <div>
                      <button
                        type="button"
                        onClick={() => setSelectedId(i.id)}
                        style={{
                          padding: '4px 10px',
                          fontSize: 12,
                          background: 'transparent',
                          color: 'var(--c-ink-2)',
                          border: '1px solid var(--c-line-2)',
                          borderRadius: 6,
                          cursor: 'pointer',
                        }}
                      >
                        Open
                      </button>
                    </div>
                    <div>
                      {i.youtube_url ? (
                        <a
                          href={i.youtube_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: 'var(--c-accent, #2a5b3a)', fontSize: 12 }}
                        >
                          link →
                        </a>
                      ) : (
                        <span style={{ color: 'var(--c-ink-3)', fontSize: 12 }}>—</span>
                      )}
                    </div>
                  </div>
                );
              })}
          </div>
        )}
      </Section>

      <div style={{ marginTop: 18 }}>
        <Link href="/admin/upsc" style={{ fontSize: 13, color: 'var(--c-ink-2)' }}>
          ← Back to digest list
        </Link>
      </div>
    </AdminShell>
  );
}

/* shared <select> styling (matches admin-shell Select inner styles) */
const selectStyle: React.CSSProperties = {
  width: '100%',
  padding: '9px 12px',
  borderRadius: 8,
  border: '1px solid var(--c-line-2)',
  background: 'var(--c-surface-2)',
  fontSize: 13.5,
  outline: 'none',
  fontFamily: 'inherit',
};
