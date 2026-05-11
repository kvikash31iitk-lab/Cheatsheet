'use client';

import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { AppBar } from '@/components/app-bar';
import { Btn, Tag } from '@/components/ui';
import { Ic } from '@/components/icons';
import { createJob, getPreview, getMe, type JobKind, type Preview, type Me } from '@/lib/api';

const YT_RE = /^https?:\/\/(www\.)?(youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/)[\w-]{11}/;

export default function GeneratePage() {
  return (
    <Suspense fallback={<GeneratePageShell />}>
      <GenerateForm />
    </Suspense>
  );
}

function GeneratePageShell() {
  return (
    <main style={{ minHeight: '100vh' }}>
      <AppBar />
      <div style={{ padding: 32, maxWidth: 760, margin: '0 auto' }}>
        <div style={{ fontSize: 14, color: 'var(--c-ink-3)' }}>Loading…</div>
      </div>
    </main>
  );
}

function GenerateForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [url, setUrl] = useState(() => searchParams?.get('url') ?? '');
  const [kind, setKind] = useState<JobKind>(
    () => ((searchParams?.get('kind') as JobKind) ?? 'cheatsheet'),
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    getMe().then(setMe).catch(() => {});
  }, []);

  const valid = YT_RE.test(url);

  // Debounced preview fetch when URL becomes valid
  useEffect(() => {
    if (!valid) {
      setPreview(null);
      setPreviewError(null);
      return;
    }
    setPreviewLoading(true);
    setPreviewError(null);
    const t = setTimeout(() => {
      getPreview(url)
        .then((p) => {
          setPreview(p);
          setPreviewLoading(false);
        })
        .catch((e) => {
          setPreviewError(e instanceof Error ? e.message : String(e));
          setPreviewLoading(false);
        });
    }, 400);
    return () => clearTimeout(t);
  }, [url, valid]);

  // If both url + kind came from the dashboard QuickGenerate, auto-submit
  // once preview returns.
  useEffect(() => {
    const fromDash = searchParams?.get('url') && searchParams?.get('kind');
    if (fromDash && preview && !submitting) {
      submit();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview]);

  async function submit() {
    if (!valid || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const { id } = await createJob(url, kind);
      router.push(`/generate/${id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  }

  return (
    <main style={{ minHeight: '100vh' }}>
      <AppBar />
      <div style={{ padding: 32, maxWidth: 760, margin: '0 auto' }}>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            color: 'var(--c-ink-3)',
            letterSpacing: '.08em',
            marginBottom: 8,
            textTransform: 'uppercase',
          }}
        >
          New generation
        </div>
        <h1
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 44,
            fontWeight: 400,
            letterSpacing: '-0.02em',
            margin: '0 0 8px',
            color: 'var(--c-ink)',
          }}
        >
          Paste a YouTube link to begin.
        </h1>
        <p style={{ fontSize: 14.5, color: 'var(--c-ink-2)', margin: '0 0 28px' }}>
          We'll fetch the transcript, extract key visuals, and generate your notes.
        </p>

        <label
          style={{
            fontSize: 12.5,
            fontWeight: 500,
            color: 'var(--c-ink-2)',
            marginBottom: 8,
            display: 'block',
          }}
        >
          YouTube URL
        </label>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '0 14px',
            background: 'var(--c-surface)',
            border: `1.5px solid ${
              url && !valid ? 'var(--c-error)' : valid ? 'var(--c-accent)' : 'var(--c-line-2)'
            }`,
            borderRadius: 10,
            height: 48,
            marginBottom: 24,
          }}
        >
          <Ic.yt size={18} />
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=..."
            style={{
              flex: 1,
              border: 'none',
              outline: 'none',
              background: 'transparent',
              fontFamily: 'var(--font-mono)',
              fontSize: 13,
              color: 'var(--c-ink)',
            }}
            autoFocus
          />
          {valid && !previewLoading && preview && (
            <Tag tone="mint">
              <Ic.check size={10} /> Valid
            </Tag>
          )}
          {previewLoading && <Tag tone="neutral">Loading…</Tag>}
          {url && !valid && <Tag tone="error">Invalid URL</Tag>}
        </div>

        {/* Preview card */}
        {preview && (
          <div
            style={{
              display: 'flex',
              gap: 16,
              padding: 14,
              background: 'var(--c-surface)',
              border: '1px solid var(--c-line)',
              borderRadius: 12,
              marginBottom: 24,
            }}
          >
            <div
              style={{
                width: 144,
                height: 81,
                borderRadius: 8,
                background: `url(${preview.thumbnail_url}) center/cover, linear-gradient(135deg, #2a3658, #1a2440)`,
                position: 'relative',
                flex: 'none',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  position: 'absolute',
                  bottom: 5,
                  right: 5,
                  fontSize: 10,
                  fontFamily: 'var(--font-mono)',
                  color: '#fff',
                  background: 'rgba(0,0,0,.8)',
                  padding: '1px 5px',
                  borderRadius: 3,
                }}
              >
                {formatDuration(preview.duration_seconds)}
              </div>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  color: 'var(--c-ink)',
                  marginBottom: 4,
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                }}
              >
                {preview.title}
              </div>
              <div
                style={{
                  fontSize: 12.5,
                  color: 'var(--c-ink-3)',
                  marginBottom: 8,
                  fontFamily: 'var(--font-mono)',
                }}
              >
                {preview.video_id}
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {(() => {
                  const freeLeft =
                    kind === 'cheatsheet'
                      ? (me?.free_cheatsheets_left ?? 0)
                      : (me?.free_books_left ?? 0);
                  const cost = preview.cost_paise[kind];
                  const walletPaise = me?.wallet_balance_paise ?? 0;
                  if (freeLeft > 0) {
                    return (
                      <Tag tone="mint">
                        <Ic.check size={10} /> Free · {freeLeft} {kind === 'cheatsheet' ? 'cheat' : 'book'}{freeLeft === 1 ? '' : 's'} left today
                      </Tag>
                    );
                  }
                  if (walletPaise >= cost) {
                    return (
                      <Tag tone="accent">
                        ₹{(cost / 100).toFixed(0)} from wallet
                      </Tag>
                    );
                  }
                  return (
                    <Tag tone="error">
                      Need ₹{(cost / 100).toFixed(0)} — wallet has ₹{(walletPaise / 100).toFixed(2)}
                    </Tag>
                  );
                })()}
                <Tag tone="neutral">
                  ~{kind === 'cheatsheet' ? 30 : 120}s to generate
                </Tag>
              </div>
            </div>
          </div>
        )}
        {previewError && (
          <div
            style={{
              background: 'var(--c-error-bg)',
              color: 'var(--c-error)',
              padding: 12,
              borderRadius: 10,
              fontSize: 13,
              marginBottom: 16,
            }}
          >
            {previewError}
          </div>
        )}

        <label
          style={{
            fontSize: 12.5,
            fontWeight: 500,
            color: 'var(--c-ink-2)',
            marginBottom: 8,
            display: 'block',
          }}
        >
          Output type
        </label>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 28 }}>
          <KindCard
            kind="cheatsheet"
            selected={kind === 'cheatsheet'}
            onClick={() => setKind('cheatsheet')}
            icon={<Ic.zap size={16} />}
            title="Cheatsheet"
            sub="Single page · key terms, formulas, structure."
            time="~30 seconds"
          />
          <KindCard
            kind="book"
            selected={kind === 'book'}
            onClick={() => setKind('book')}
            icon={<Ic.book size={16} />}
            title="Book Notes"
            sub="Chapter-by-chapter writeup with examples and screenshots."
            time="~2 minutes"
          />
        </div>

        {error && (
          <div
            style={{
              background: 'var(--c-error-bg)',
              color: 'var(--c-error)',
              padding: 12,
              borderRadius: 10,
              fontSize: 13,
              marginBottom: 16,
            }}
          >
            {error}
          </div>
        )}

        {(() => {
          if (!preview) return null;
          const freeLeft =
            kind === 'cheatsheet'
              ? (me?.free_cheatsheets_left ?? 0)
              : (me?.free_books_left ?? 0);
          const cost = preview.cost_paise[kind];
          const walletPaise = me?.wallet_balance_paise ?? 0;
          const willCost = freeLeft === 0;
          const cantAfford = willCost && walletPaise < cost;
          if (cantAfford) {
            return (
              <div
                style={{
                  background: 'var(--c-error-bg)',
                  color: 'var(--c-error)',
                  padding: 12,
                  borderRadius: 10,
                  fontSize: 13,
                  marginBottom: 16,
                }}
              >
                Today's free {kind === 'cheatsheet' ? 'cheatsheets' : 'book notes'}{' '}
                are used. This {Math.round(preview.duration_seconds / 60)}-min
                video would cost <b>₹{(cost / 100).toFixed(0)}</b> from your
                wallet (you have ₹{(walletPaise / 100).toFixed(2)}).{' '}
                <a
                  href="/wallet"
                  style={{ color: 'inherit', textDecoration: 'underline' }}
                >
                  Top up
                </a>{' '}
                to continue.
              </div>
            );
          }
          if (willCost) {
            return (
              <div
                style={{
                  background: 'var(--c-accent-2)',
                  color: 'var(--c-accent-ink)',
                  padding: 12,
                  borderRadius: 10,
                  fontSize: 13,
                  marginBottom: 16,
                }}
              >
                Today's free {kind === 'cheatsheet' ? 'cheatsheets' : 'book notes'}{' '}
                are used. This generation will debit{' '}
                <b>₹{(cost / 100).toFixed(0)}</b> from your wallet (balance:
                ₹{(walletPaise / 100).toFixed(2)}).
              </div>
            );
          }
          return null;
        })()}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Btn
            variant="accent"
            size="lg"
            icon={<Ic.sparkle size={14} />}
            disabled={(() => {
              if (!valid || submitting || previewLoading || !!previewError) {
                return true;
              }
              if (!preview) return true;
              const freeLeft =
                kind === 'cheatsheet'
                  ? (me?.free_cheatsheets_left ?? 0)
                  : (me?.free_books_left ?? 0);
              const cost = preview.cost_paise[kind];
              const walletPaise = me?.wallet_balance_paise ?? 0;
              return freeLeft === 0 && walletPaise < cost;
            })()}
            onClick={submit}
          >
            {submitting ? 'Starting…' : 'Generate now'}
          </Btn>
        </div>
      </div>
    </main>
  );
}

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
  return `${m}:${String(sec).padStart(2, '0')}`;
}

function KindCard({
  selected,
  onClick,
  icon,
  title,
  sub,
  time,
}: {
  kind: JobKind;
  selected: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  sub: string;
  time: string;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: 18,
        borderRadius: 12,
        border: `1.5px solid ${selected ? 'var(--c-accent)' : 'var(--c-line-2)'}`,
        background: selected ? 'var(--c-accent-2)' : 'var(--c-surface)',
        textAlign: 'left',
        cursor: 'pointer',
        fontFamily: 'inherit',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {icon}
          <span
            style={{
              fontSize: 14.5,
              fontWeight: 600,
              color: selected ? 'var(--c-accent-ink)' : 'var(--c-ink)',
            }}
          >
            {title}
          </span>
        </div>
        <div
          style={{
            width: 16,
            height: 16,
            borderRadius: '50%',
            background: selected ? 'var(--c-accent)' : 'transparent',
            border: selected ? 'none' : '1.5px solid var(--c-line-2)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
          }}
        >
          {selected && <Ic.check size={10} sw={2.5} />}
        </div>
      </div>
      <div
        style={{
          fontSize: 12.5,
          color: selected ? 'var(--c-accent-ink)' : 'var(--c-ink-3)',
          lineHeight: 1.45,
          opacity: selected ? 0.85 : 1,
        }}
      >
        {sub}
      </div>
      <div
        style={{
          marginTop: 10,
          fontSize: 11,
          color: selected ? 'var(--c-accent-ink)' : 'var(--c-ink-3)',
          fontFamily: 'var(--font-mono)',
        }}
      >
        {time}
      </div>
    </button>
  );
}
