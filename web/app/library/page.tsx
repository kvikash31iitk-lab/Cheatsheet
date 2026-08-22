'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { AppBar } from '@/components/app-bar';
import { Btn, Tag } from '@/components/ui';
import { Ic } from '@/components/icons';
import { getLibrary, listPlaylists, retryPlaylistJob, type Job } from '@/lib/api';


type Filter = 'all' | 'cheatsheet' | 'book' | 'playlist' | 'failed';

export default function LibraryPage() {
  const [items, setItems] = useState<Job[] | null>(null);
  const [playlists, setPlaylists] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');

  useEffect(() => {
    getLibrary()
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    listPlaylists()
      .then(setPlaylists)
      .catch(() => {});
  }, []);


  const counts = useMemo(() => {
    if (!items) return { all: 0, cheatsheet: 0, book: 0, failed: 0 };
    return items.reduce(
      (acc, j) => {
        acc.all++;
        if (j.kind === 'cheatsheet') acc.cheatsheet++;
        if (j.kind === 'book') acc.book++;
        if (j.status.state === 'error') acc.failed++;
        return acc;
      },
      { all: 0, cheatsheet: 0, book: 0, failed: 0 },
    );
  }, [items]);

  const filtered = useMemo(() => {
    if (!items) return [];
    const q = query.trim().toLowerCase();
    return items.filter((j) => {
      if (filter === 'cheatsheet' && j.kind !== 'cheatsheet') return false;
      if (filter === 'book' && j.kind !== 'book') return false;
      if (filter === 'failed' && j.status.state !== 'error') return false;
      if (q) {
        const title = j.meta?.title?.toLowerCase() ?? '';
        const ch = j.meta?.channel?.toLowerCase() ?? '';
        if (!title.includes(q) && !ch.includes(q)) return false;
      }
      return true;
    });
  }, [items, filter, query]);

  return (
    <main style={{ minHeight: '100vh' }}>
      <AppBar />

      <div style={{ padding: 32, maxWidth: 1200, margin: '0 auto' }}>
        {/* Title block */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-end',
            marginBottom: 24,
          }}
        >
          <div>
            <div
              style={{
                fontSize: 11.5,
                color: 'var(--c-ink-3)',
                fontFamily: 'var(--font-mono)',
                letterSpacing: '.08em',
                marginBottom: 4,
                textTransform: 'uppercase',
              }}
            >
              Library
            </div>
            <h1
              style={{
                fontFamily: 'var(--font-serif)',
                fontSize: 36,
                fontWeight: 400,
                letterSpacing: '-0.015em',
                margin: 0,
                color: 'var(--c-ink)',
              }}
            >
              All your generated notes.
            </h1>
          </div>
          <Link href="/generate" style={{ textDecoration: 'none' }}>
            <Btn variant="primary" size="md" icon={<Ic.plus size={13} />}>
              New generation
            </Btn>
          </Link>
        </div>

        {/* Toolbar */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 18,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '8px 12px',
              background: 'var(--c-surface)',
              border: '1px solid var(--c-line-2)',
              borderRadius: 8,
              width: 320,
            }}
          >
            <Ic.search size={14} />
            <input
              placeholder="Search title or channel…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{
                flex: 1,
                border: 'none',
                background: 'transparent',
                fontSize: 13,
                outline: 'none',
              }}
            />
          </div>
        </div>

        {/* Tab pills */}
        <div
          style={{
            display: 'flex',
            gap: 6,
            marginBottom: 20,
            borderBottom: '1px solid var(--c-line)',
          }}
        >
          {(
            [
              { l: 'All', k: 'all', n: counts.all + playlists.length },
              { l: 'Cheatsheets', k: 'cheatsheet', n: counts.cheatsheet },
              { l: 'Book Notes', k: 'book', n: counts.book },
              { l: 'Playlists', k: 'playlist', n: playlists.length },
              { l: 'Failed', k: 'failed', n: counts.failed },
            ] as { l: string; k: Filter; n: number }[]
          ).map((t) => {
            const active = filter === t.k;
            return (
              <button
                key={t.k}
                onClick={() => setFilter(t.k)}
                style={{
                  padding: '10px 14px',
                  border: 'none',
                  background: 'transparent',
                  fontSize: 13,
                  fontWeight: active ? 600 : 400,
                  color: active ? 'var(--c-ink)' : 'var(--c-ink-3)',
                  borderBottom: active
                    ? '2px solid var(--c-accent)'
                    : '2px solid transparent',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  fontFamily: 'inherit',
                }}
              >
                {t.l}{' '}
                <span
                  style={{
                    fontSize: 11,
                    color: 'var(--c-ink-3)',
                    fontFamily: 'var(--font-mono)',
                  }}
                >
                  {t.n}
                </span>
              </button>
            );
          })}
        </div>

        {error && (
          <div
            style={{
              background: 'var(--c-error-bg)',
              color: 'var(--c-error)',
              padding: 16,
              borderRadius: 10,
              fontSize: 13,
              marginBottom: 16,
            }}
          >
            {error}
          </div>
        )}

        {/* Playlist section when filter is 'playlist' or 'all' */}
        {(filter === 'playlist' || filter === 'all') && playlists.length > 0 && (
          <div style={{ marginBottom: 32 }}>
            {filter === 'all' && (
              <h2 style={{ fontSize: 16, fontWeight: 600, color: 'var(--c-ink)', marginBottom: 12 }}>
                📑 Playlists ({playlists.length})
              </h2>
            )}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                gap: 16,
              }}
            >
              {playlists.map((pl) => (
                <PlaylistCard
                  key={pl.id}
                  pl={pl}
                  onReload={() => listPlaylists().then(setPlaylists).catch(() => {})}
                />
              ))}

            </div>
          </div>
        )}


        {/* Single Video Grid */}
        {filter !== 'playlist' && (
          items && filtered.length === 0 ? (
            <EmptyState filter={filter} hasAny={items.length > 0} />
          ) : (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                gap: 16,
              }}
            >
              {filtered.map((j) => (
                <NoteCard key={j.id} job={j} />
              ))}
            </div>
          )
        )}

      </div>
    </main>
  );
}

function PlaylistCard({ pl, onReload }: { pl: any; onReload?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const items = pl.items || [];
  const completedCount = items.filter((it: any) => it.status === 'complete' || it.has_pdf).length;
  const hasRemaining = items.some((it: any) => it.status === 'failed' || it.status === 'pending' || !it.has_pdf);
  const isRunning = pl.status === 'running';

  const handleRetry = async () => {
    try {
      setRetrying(true);
      await retryPlaylistJob(pl.id);
      if (onReload) onReload();
    } catch (e: any) {
      alert(e?.message || 'Failed to retry playlist');
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div
      style={{
        background: 'var(--c-surface)',
        border: '1.5px solid var(--c-accent)',
        borderRadius: 12,
        padding: 16,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
      }}
    >
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <Tag tone="accent">PLAYLIST</Tag>
            {isRunning && <Tag tone="mint">⚡ Processing</Tag>}
          </div>
          <span style={{ fontSize: 11, color: 'var(--c-ink-3)', fontFamily: 'var(--font-mono)' }}>
            {completedCount} / {pl.total_videos || items.length} Completed
          </span>
        </div>
        <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--c-ink)', marginBottom: 8, wordBreak: 'break-all' }}>
          {pl.playlist_url}
        </div>
      </div>

      <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <a
            href={`/api/playlist/download/${pl.id}/master`}
            target="_blank"
            rel="noreferrer"
            style={{ textDecoration: 'none', flex: 1, minWidth: 120 }}
          >
            <Btn variant="accent" size="sm" style={{ width: '100%' }}>
              📄 Master PDF
            </Btn>
          </a>
          <a
            href={`/api/playlist/download/${pl.id}/zip`}
            target="_blank"
            rel="noreferrer"
            style={{ textDecoration: 'none', flex: 1, minWidth: 120 }}
          >
            <Btn variant="primary" size="sm" style={{ width: '100%' }}>
              📦 Download ZIP (All)
            </Btn>
          </a>
        </div>

        {hasRemaining && (
          <Btn
            variant="secondary"
            size="sm"
            onClick={handleRetry}
            disabled={retrying || isRunning}
            style={{ width: '100%', borderColor: 'var(--c-accent)', color: 'var(--c-accent)', fontWeight: 600 }}
          >
            {retrying ? '🔄 Starting Retry...' : isRunning ? '⚡ In Progress...' : '🔄 Retry Remaining Videos'}
          </Btn>
        )}



        {items.length > 0 && (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            style={{
              padding: '8px 12px',
              borderRadius: 6,
              border: '1px solid var(--c-line)',
              background: 'var(--c-surface-2)',
              color: 'var(--c-ink)',
              fontSize: 12,
              cursor: 'pointer',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <span>📹 View Individual Video Cheatsheets ({items.length})</span>
            <span>{expanded ? '▲' : '▼'}</span>
          </button>
        )}

        {expanded && (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 220, overflowY: 'auto', paddingRight: 4 }}>
            {items.map((it: any) => (
              <div
                key={it.item_key}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '6px 8px',
                  background: 'var(--c-surface-2)',
                  borderRadius: 6,
                  fontSize: 12,
                }}
              >
                <span
                  style={{
                    color: 'var(--c-ink)',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    maxWidth: 200,
                  }}
                  title={it.title}
                >
                  {it.title}
                </span>
                {it.has_pdf ? (
                  <a
                    href={`/api/playlist/download/${pl.id}/item/${it.item_key}`}
                    target="_blank"
                    rel="noreferrer"
                    style={{ textDecoration: 'none', color: 'var(--c-accent)', fontWeight: 600 }}
                  >
                    PDF ⬇️
                  </a>
                ) : (
                  <span style={{ color: 'var(--c-ink-3)', fontSize: 11 }}>Pending</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState({ filter, hasAny }: { filter: Filter; hasAny: boolean }) {

  const msg =
    !hasAny
      ? 'No generations yet. Paste a YouTube link to make your first one.'
      : `No ${filter === 'all' ? 'matching' : filter} items.`;
  return (
    <div
      style={{
        background: 'var(--c-surface-2)',
        border: '1px dashed var(--c-line-2)',
        borderRadius: 14,
        padding: 48,
        textAlign: 'center',
      }}
    >
      <div style={{ fontSize: 14.5, color: 'var(--c-ink-2)', marginBottom: 16 }}>
        {msg}
      </div>
      {!hasAny && (
        <Link href="/generate" style={{ textDecoration: 'none' }}>
          <Btn variant="accent" size="md" icon={<Ic.sparkle size={14} />}>
            Generate your first
          </Btn>
        </Link>
      )}
    </div>
  );
}

function NoteCard({ job }: { job: Job }) {
  const meta = job.meta;
  const isFailed = job.status.state === 'error';
  const isDone = job.status.state === 'done';
  const isCheat = job.kind === 'cheatsheet';

  return (
    <Link
      href={`/generate/${job.id}`}
      style={{ textDecoration: 'none', color: 'inherit' }}
    >
      <article
        style={{
          background: 'var(--c-surface)',
          border: '1px solid var(--c-line)',
          borderRadius: 12,
          overflow: 'hidden',
          cursor: 'pointer',
        }}
      >
        {/* Thumb */}
        <div
          style={{
            aspectRatio: '16/9',
            background: meta?.thumbnail_url
              ? `url(${meta.thumbnail_url}) center/cover`
              : 'linear-gradient(135deg, #2a3658, #1a2440)',
            position: 'relative',
          }}
        >
          {!meta?.thumbnail_url && (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'rgba(255,255,255,.6)',
              }}
            >
              <div
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: '50%',
                  background: 'rgba(255,255,255,.15)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Ic.play size={14} />
              </div>
            </div>
          )}
          <div style={{ position: 'absolute', top: 10, left: 10 }}>
            <Tag
              tone={isCheat ? 'accent' : 'ink'}
              style={{
                background: isCheat ? 'rgba(240,228,212,.95)' : 'rgba(28,25,22,.92)',
                color: isCheat ? 'var(--c-accent-ink)' : '#fff',
              }}
            >
              {isCheat ? (
                <>
                  <Ic.zap size={10} /> Cheatsheet
                </>
              ) : (
                <>
                  <Ic.book size={10} /> Book Notes
                </>
              )}
            </Tag>
          </div>
          {meta?.duration_seconds ? (
            <div
              style={{
                position: 'absolute',
                bottom: 10,
                right: 10,
                fontSize: 10.5,
                fontFamily: 'var(--font-mono)',
                color: '#fff',
                background: 'rgba(0,0,0,.75)',
                padding: '2px 6px',
                borderRadius: 3,
              }}
            >
              {formatDuration(meta.duration_seconds)}
            </div>
          ) : null}
          {isFailed && (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                background: 'rgba(184,66,58,.6)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                fontSize: 11,
                fontWeight: 600,
                fontFamily: 'var(--font-mono)',
              }}
            >
              FAILED
            </div>
          )}
          {!isDone && !isFailed && (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                background: 'rgba(28,25,22,.55)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#e8a583',
                fontSize: 11,
                fontWeight: 600,
                fontFamily: 'var(--font-mono)',
                letterSpacing: '.08em',
              }}
            >
              ● PROCESSING
            </div>
          )}
        </div>
        {/* Body */}
        <div style={{ padding: 16 }}>
          <div
            style={{
              fontSize: 13.5,
              fontWeight: 500,
              color: 'var(--c-ink)',
              lineHeight: 1.35,
              marginBottom: 6,
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
              minHeight: 36,
            }}
          >
            {meta?.title || 'Untitled'}
          </div>
          <div
            style={{
              fontSize: 11.5,
              color: 'var(--c-ink-3)',
              marginBottom: 12,
              minHeight: 16,
            }}
          >
            {meta?.channel || ''}
          </div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              fontSize: 11,
              color: 'var(--c-ink-3)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            <span>{relativeTime(job.created_at)}</span>
            <span>{isCheat ? 'cheat' : 'book'}</span>
          </div>
        </div>
      </article>
    </Link>
  );
}

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
  return `${m}:${String(sec).padStart(2, '0')}`;
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diff = Math.max(0, now - then);
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}
