'use client';

import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { AppBar } from '@/components/app-bar';
import { Btn, Tag } from '@/components/ui';
import { Ic } from '@/components/icons';
import {
  createJob,
  createPlaylistJob,
  retryPlaylistJob,
  stopPlaylistJob,
  friendlyGenerationError,
  getPreview,
  getMe,
  type JobKind,
  type Preview,
  type Me,
  type FeatureFlag,
} from '@/lib/api';




// Tile metadata for the optional-features section. Order matches the
// backend's FEATURE_ORDER so the UI reads top-to-bottom in the same shape
// the cache key hashes. Keep flag values literal so TypeScript narrows.
const FEATURE_TILES: ReadonlyArray<{
  flag: FeatureFlag;
  title: string;
  sub: string;
}> = [
  { flag: 'summary', title: 'Summary card',     sub: 'Cover-page TL;DR + 3 takeaways + difficulty.' },
  { flag: 'tldr',    title: 'Section TL;DRs',   sub: 'A one-line preview at the start of each section.' },
  { flag: 'qna',     title: 'Self-Test',        sub: '5–8 review Q&A appended at the end.' },
  { flag: 'mermaid', title: 'Mindmap & flow',   sub: 'Auto-generated diagram pages from the topic.' },
  { flag: 'chapters',title: 'Index + QR',       sub: 'Chapter index page and a QR back to the video.' },
];

const YT_RE = /^https?:\/\/(www\.)?(youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/(?:shorts|live)\/)[\w-]{11}/;
const PLAYLIST_RE = /^https?:\/\/(www\.)?youtube\.com\/(playlist\?list=|watch\?.*[?&]list=)[\w-]+/i;



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
  const [mode, setMode] = useState<'single' | 'playlist'>('single');
  const [url, setUrl] = useState(() => searchParams?.get('url') ?? '');
  const [kind, setKind] = useState<JobKind>(
    () => ((searchParams?.get('kind') as JobKind) ?? 'cheatsheet'),
  );
  const [maxVideos, setMaxVideos] = useState<number>(100);
  const [concurrency, setConcurrency] = useState<number>(3);
  const [delaySeconds, setDelaySeconds] = useState<number>(2);
  const [playlistJobId, setPlaylistJobId] = useState<string | null>(null);
  const [playlistStatus, setPlaylistStatus] = useState<any>(null);


  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [features, setFeatures] = useState<Set<FeatureFlag>>(new Set());
  const toggleFeature = (flag: FeatureFlag) =>
    setFeatures((prev) => {
      const next = new Set(prev);
      if (next.has(flag)) next.delete(flag);
      else next.add(flag);
      return next;
    });

  useEffect(() => {
    getMe().then(setMe).catch(() => {});
  }, []);

  const valid = YT_RE.test(url);

  // Automatic intelligent URL mode detection:
  // If user pastes a playlist link -> auto switch to playlist mode.
  // If user pastes a single video link -> auto switch to single mode.
  useEffect(() => {
    const trimmed = url.trim();
    if (!trimmed) return;
    if (PLAYLIST_RE.test(trimmed)) {
      if (mode !== 'playlist') setMode('playlist');
    } else if (YT_RE.test(trimmed)) {
      if (mode !== 'single') setMode('single');
    }
  }, [url, mode]);

  // Debounced preview fetch when URL becomes valid (single video mode only)
  useEffect(() => {
    if (!valid || mode === 'playlist') {
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
          setPreviewError(friendlyGenerationError(e));
          setPreviewLoading(false);
        });
    }, 400);
    return () => clearTimeout(t);
  }, [url, valid, mode]);

  // Restore active playlist job from localStorage on mount with instant status fetch (< 500ms)
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const savedJobId = localStorage.getItem('active_playlist_job_id');
      if (savedJobId) {
        setPlaylistJobId(savedJobId);
        // Instant non-blocking status fetch on mount
        fetch(`/api/playlist/status/${encodeURIComponent(savedJobId)}`)
          .then((res) => (res.ok ? res.json() : null))
          .then((data) => {
            if (data && (data.status === 'running' || data.status === 'complete' || data.status === 'interrupted' || data.status === 'stopped')) {
              setPlaylistStatus(data);
            }
          })
          .catch(() => {});
      }
    }
  }, []);

  useEffect(() => {
    if (!playlistJobId) return;
    const jobId: string = playlistJobId;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function pollPlaylist() {
      try {
        const res = await fetch(`/api/playlist/status/${encodeURIComponent(jobId)}`);
        if (!res.ok) {
          if (typeof window !== 'undefined') localStorage.removeItem('active_playlist_job_id');
          return;
        }
        const data = await res.json();
        if (cancelled) return;
        setPlaylistStatus(data);
        if (data.status === 'running') {
          timer = setTimeout(pollPlaylist, 3000);
        }
      } catch (e) {
        console.error('Playlist status error', e);
      }
    }

    pollPlaylist();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [playlistJobId]);





  async function submit() {
    const isPlaylistMode = mode === 'playlist';
    const isUrlValid = isPlaylistMode ? PLAYLIST_RE.test(url.trim()) : valid;
    if (!isUrlValid || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      if (isPlaylistMode) {
        const { id } = await createPlaylistJob(url.trim(), kind, delaySeconds, maxVideos, concurrency);
        if (typeof window !== 'undefined') {
          localStorage.setItem('active_playlist_job_id', id);
        }
        setPlaylistJobId(id);
        setSubmitting(false);
        setPlaylistStatus({ status: 'running', progress: 'Extracting playlist info...' });
      } else {
        const { id } = await createJob(url, kind, Array.from(features));
        router.push(`/generate/${id}`);
      }
    } catch (e: any) {
      setError(friendlyGenerationError(e));
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

        {/* Mode Selector Tabs */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 24 }}>
          <button
            type="button"
            onClick={() => { setMode('single'); setUrl(''); }}
            style={{
              flex: 1,
              padding: '10px 16px',
              borderRadius: 8,
              border: `1.5px solid ${mode === 'single' ? 'var(--c-accent)' : 'var(--c-line)'}`,
              background: mode === 'single' ? 'var(--c-surface-2)' : 'transparent',
              color: 'var(--c-ink)',
              fontWeight: mode === 'single' ? 600 : 400,
              cursor: 'pointer',
              fontSize: 14,
            }}
          >
            📹 Single Video
          </button>
          <button
            type="button"
            onClick={() => { setMode('playlist'); setUrl(''); }}
            style={{
              flex: 1,
              padding: '10px 16px',
              borderRadius: 8,
              border: `1.5px solid ${mode === 'playlist' ? 'var(--c-accent)' : 'var(--c-line)'}`,
              background: mode === 'playlist' ? 'var(--c-surface-2)' : 'transparent',
              color: 'var(--c-ink)',
              fontWeight: mode === 'playlist' ? 600 : 400,
              cursor: 'pointer',
              fontSize: 14,
            }}
          >
            📑 Playlist Extraction
          </button>
        </div>

        {/* Live Playlist Progress Dashboard Banner */}
        {(playlistStatus || mode === 'playlist') && (() => {
          if (!playlistStatus) return null;
          // Extract percentage and item progress if available in manifest or string
          const manifest = playlistStatus.manifest;

          const total = manifest?.total_videos || playlistStatus.summary?.total_videos || 0;
          const completedCount = manifest?.items
            ? Object.values(manifest.items).filter((i: any) => i.status === 'complete').length
            : 0;
          const itemsList: any[] = manifest?.items ? Object.values(manifest.items) : [];
          const failedCount = itemsList.filter((i: any) => i.status === 'failed').length;
          const percent = total > 0 ? Math.round((completedCount / total) * 100) : (playlistStatus.status === 'complete' ? 100 : 0);

          return (
            <div
              style={{
                padding: 20,
                background: 'var(--c-surface)',
                border: '1.5px solid var(--c-accent)',
                borderRadius: 12,
                marginBottom: 24,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div style={{ fontWeight: 600, fontSize: 15, color: 'var(--c-ink)' }}>
                  📑 Playlist Processing Progress
                </div>
                <Tag tone={playlistStatus.status === 'complete' ? 'mint' : playlistStatus.status === 'error' ? 'error' : 'accent'}>
                  {playlistStatus.status?.toUpperCase()}
                </Tag>
              </div>

              {/* Progress Bar */}
              <div style={{ background: 'var(--c-line)', borderRadius: 6, height: 10, width: '100%', overflow: 'hidden', marginBottom: 12 }}>
                <div
                  style={{
                    background: playlistStatus.status === 'complete' ? 'var(--c-mint)' : 'var(--c-accent)',
                    height: '100%',
                    width: `${percent}%`,
                    transition: 'width 0.4s ease',
                  }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: 'var(--c-ink-2)', marginBottom: 8 }}>
                <span style={{ fontWeight: 500 }}>{playlistStatus.progress || 'Processing in background...'}</span>
                {total > 0 && <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{completedCount} / {total} Videos ({percent}%)</span>}
              </div>

              {/* Multi-Worker Active Parallel Tasks Banner */}
              {playlistStatus.status === 'running' && itemsList.filter((i: any) => i.status === 'running').length > 0 && (
                <div
                  style={{
                    marginBottom: 14,
                    padding: '12px 14px',
                    background: 'var(--c-surface-2)',
                    border: '1.5px solid var(--c-accent)',
                    borderRadius: 8,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--c-accent)', textTransform: 'uppercase', letterSpacing: '.05em' }}>
                      ⚡ Active Parallel Workers ({itemsList.filter((i: any) => i.status === 'running').length} running simultaneously)
                    </span>
                  </div>
                  {itemsList
                    .filter((i: any) => i.status === 'running')
                    .map((it: any) => (
                      <div key={it.key} style={{ padding: '6px 10px', background: 'rgba(232, 165, 131, 0.08)', borderRadius: 6, border: '1px solid var(--c-line)' }}>
                        <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--c-ink)' }}>
                          Video {it.index}: {it.title}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--c-accent)', fontFamily: 'var(--font-mono)', marginTop: 2 }}>
                          <span style={{ animation: 'pulse 1.5s infinite' }}>●</span>
                          <span>{it.current_subtask || 'Processing...'}</span>
                        </div>
                      </div>
                    ))}
                </div>
              )}


              {/* Live Video Log List */}
              {itemsList.length > 0 && (
                <div style={{ marginTop: 12, borderTop: '1px solid var(--c-line-2)', paddingTop: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--c-ink-2)' }}>
                      Live Video Log ({itemsList.length} items):
                    </div>
                    {playlistStatus.status === 'running' && playlistJobId && (
                      <button
                        type="button"
                        onClick={async () => {
                          try {
                            setPlaylistStatus({ ...playlistStatus, status: 'stopped', progress: 'Process stopped by user.' });
                            await stopPlaylistJob(playlistJobId);
                          } catch (e) {
                            console.error('Stop failed', e);
                          }
                        }}
                        style={{
                          padding: '4px 10px',
                          borderRadius: 6,
                          background: 'transparent',
                          color: 'var(--c-error)',
                          border: '1px solid var(--c-error)',
                          fontSize: 11.5,
                          fontWeight: 600,
                          cursor: 'pointer',
                          fontFamily: 'inherit',
                        }}
                      >
                        ⏹️ Stop Process
                      </button>
                    )}
                    {failedCount > 0 && playlistStatus.status !== 'running' && (
                      <button
                        type="button"
                        onClick={async () => {
                          if (!playlistJobId) return;
                          try {
                            setPlaylistStatus({ ...playlistStatus, status: 'running', progress: `Retrying ${failedCount} failed video(s)...` });
                            await retryPlaylistJob(playlistJobId);
                          } catch (e) {
                            console.error('Retry failed', e);
                          }
                        }}
                        style={{
                          padding: '4px 10px',
                          borderRadius: 6,
                          background: 'var(--c-accent)',
                          color: '#fff',
                          border: 'none',
                          fontSize: 11.5,
                          fontWeight: 600,
                          cursor: 'pointer',
                          fontFamily: 'inherit',
                        }}
                      >
                        🔄 Retry Failed ({failedCount})
                      </button>
                    )}

                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 320, overflowY: 'auto', paddingRight: 4 }}>
                    {itemsList.map((item: any, idx: number) => {
                      const res = item.result || {};
                      const title = res.title || item.title || `Video ${idx + 1}`;
                      const isComplete = item.status === 'complete';
                      const isFailed = item.status === 'failed';
                      const isRunning = item.status === 'running';

                      return (
                        <div
                          key={idx}
                          style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 4,
                            padding: '8px 12px',
                            borderRadius: 8,
                            background: isRunning ? 'var(--c-surface-2)' : 'var(--c-surface)',
                            fontSize: 12.5,
                            border: '1px solid var(--c-line)',
                            borderLeft: isComplete ? '4px solid var(--c-mint)' : isFailed ? '4px solid var(--c-error)' : '4px solid var(--c-accent)',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                            <span
                              style={{
                                color: 'var(--c-ink)',
                                fontWeight: 500,
                                wordBreak: 'break-word',
                                flex: 1,
                              }}
                            >
                              {isComplete ? '✅ ' : isFailed ? '❌ ' : '⚡ '} {title}
                            </span>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              {isComplete && playlistJobId && (
                                <a
                                  href={`/api/playlist/download/${playlistJobId}/item/${item.key || Object.keys(manifest?.items || {}).find(k => manifest?.items[k] === item) || item.result?.video_id || ''}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  style={{
                                    fontSize: 11.5,
                                    fontWeight: 600,
                                    color: 'var(--c-accent)',
                                    textDecoration: 'none',
                                    background: 'rgba(232, 165, 131, 0.15)',
                                    padding: '3px 8px',
                                    borderRadius: 4,
                                  }}
                                >
                                  📥 PDF
                                </a>
                              )}
                              <span
                                style={{
                                  fontSize: 11,
                                  fontWeight: 600,
                                  fontFamily: 'var(--font-mono)',
                                  color: isComplete ? 'var(--c-mint)' : isFailed ? 'var(--c-error)' : 'var(--c-accent)',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                {item.status?.toUpperCase()}
                              </span>
                            </div>
                          </div>


                          {/* Show live active subtask message for running item */}
                          {isRunning && item.current_subtask && (
                            <div
                              style={{
                                fontSize: 11.5,
                                color: 'var(--c-accent)',
                                fontFamily: 'var(--font-mono)',
                                background: 'rgba(232, 165, 131, 0.12)',
                                padding: '4px 8px',
                                borderRadius: 4,
                                marginTop: 4,
                              }}
                            >
                              ⚡ {item.current_subtask}
                            </div>
                          )}

                          {/* Show diagnostic error message if item failed */}
                          {isFailed && item.error && (
                            <div
                              style={{
                                fontSize: 11.5,
                                color: 'var(--c-error)',
                                fontFamily: 'var(--font-mono)',
                                background: 'var(--c-error-bg)',
                                padding: '4px 8px',
                                borderRadius: 4,
                                marginTop: 4,
                                wordBreak: 'break-all',
                              }}
                            >
                              ⚠️ {item.error}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}


              {playlistStatus.status === 'complete' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 14, padding: '12px 14px', background: 'var(--c-surface-2)', borderRadius: 8, border: '1px solid var(--c-mint)' }}>
                  <div style={{ fontSize: 13.5, color: 'var(--c-mint)', fontWeight: 600 }}>
                    🎉 Processed {playlistStatus.summary?.successful_videos || completedCount} / {playlistStatus.summary?.total_videos || total} videos successfully!
                  </div>
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <a
                      href={`/api/playlist/download/${playlistJobId}/master`}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 6,
                        padding: '8px 14px',
                        background: 'var(--c-accent)',
                        color: '#fff',
                        borderRadius: 6,
                        fontWeight: 600,
                        fontSize: 13,
                        textDecoration: 'none',
                      }}
                    >
                      📖 Download 70-Page Master PDF
                    </a>
                    <a
                      href={`/api/playlist/download/${playlistJobId}/zip`}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 6,
                        padding: '8px 14px',
                        background: 'transparent',
                        color: 'var(--c-ink)',
                        border: '1.5px solid var(--c-line-2)',
                        borderRadius: 6,
                        fontWeight: 600,
                        fontSize: 13,
                        textDecoration: 'none',
                      }}
                    >
                      📦 Download All 23 PDFs (ZIP)
                    </a>
                    {failedCount > 0 && playlistStatus.status !== 'running' && (
                      <button
                        type="button"
                        onClick={async () => {
                          if (!playlistJobId) return;
                          try {
                            setPlaylistStatus({ ...playlistStatus, status: 'running', progress: `Retrying ${failedCount} failed video(s)...` });
                            await retryPlaylistJob(playlistJobId);
                          } catch (e) {
                            console.error('Retry failed', e);
                          }
                        }}
                        style={{
                          padding: '8px 14px',
                          borderRadius: 6,
                          background: 'transparent',
                          color: 'var(--c-accent)',
                          border: '1.5px solid var(--c-accent)',
                          fontSize: 13,
                          fontWeight: 600,
                          cursor: 'pointer',
                          fontFamily: 'inherit',
                        }}
                      >
                        🔄 Retry Failed ({failedCount})
                      </button>
                    )}
                  </div>
                </div>
              )}

              {playlistStatus.error && (
                <div style={{ fontSize: 13, color: 'var(--c-error)', marginTop: 12 }}>
                  ❌ {playlistStatus.error}
                </div>
              )}
            </div>
          );
        })()}





        <label
          style={{
            fontSize: 12.5,
            fontWeight: 500,
            color: 'var(--c-ink-2)',
            marginBottom: 8,
            display: 'block',
          }}
        >
          {mode === 'single' ? 'YouTube Video URL' : 'YouTube Playlist URL'}
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
            placeholder={
              mode === 'single'
                ? 'https://www.youtube.com/watch?v=...'
                : 'https://www.youtube.com/playlist?list=...'
            }
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
          {(mode === 'single' ? valid : PLAYLIST_RE.test(url.trim())) && (
            <Tag tone="mint">
              <Ic.check size={10} /> Valid
            </Tag>
          )}
        </div>

        {mode === 'playlist' && (
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 16, marginBottom: 24, padding: '12px 14px', background: 'var(--c-surface)', border: '1px solid var(--c-line)', borderRadius: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--c-ink-2)' }}>⚡ Workstation Speed:</span>
              <select
                value={concurrency}
                onChange={(e) => setConcurrency(parseInt(e.target.value) || 3)}
                style={{
                  padding: '4px 10px',
                  borderRadius: 6,
                  border: '1px solid var(--c-accent)',
                  background: 'var(--c-surface-2)',
                  color: 'var(--c-accent)',
                  fontWeight: 600,
                  fontSize: 12.5,
                  cursor: 'pointer',
                }}
              >
                <option value={1}>1 Worker (Sequential)</option>
                <option value={2}>2 Workers (2x Fast)</option>
                <option value={3}>3 Workers (3x Fast - Recommended)</option>
                <option value={4}>4 Workers (4x Fast - Ultra)</option>
              </select>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--c-ink-2)' }}>Max Videos:</span>
              <input
                type="number"
                min={1}
                max={500}
                value={maxVideos}
                onChange={(e) => setMaxVideos(Math.max(1, parseInt(e.target.value) || 100))}
                style={{
                  width: 70,
                  padding: '4px 8px',
                  borderRadius: 6,
                  border: '1px solid var(--c-line)',
                  background: 'var(--c-surface-2)',
                  color: 'var(--c-ink)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 13,
                  textAlign: 'center',
                }}
              />
            </div>
          </div>
        )}




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
                <Tag tone="mint">
                  <Ic.check size={10} /> Free Generation
                </Tag>

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
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 28 }}>
          <KindCard
            kind="cheatsheet_refined"
            selected={kind === 'cheatsheet_refined'}
            onClick={() => setKind('cheatsheet_refined')}
            icon={<Ic.zap size={16} />}
            title="Refined Cheatsheet"
            sub="High-density revision · 2-column grids, zero fluff & exam traps."
            time="~30 seconds"
          />
          <KindCard
            kind="cheatsheet"
            selected={kind === 'cheatsheet'}
            onClick={() => setKind('cheatsheet')}
            icon={<Ic.zap size={16} />}
            title="Cheatsheet (Classic)"
            sub="Standard revision · key terms, formulas, structure."
            time="~30 seconds"
          />
          <KindCard
            kind="structured_notes"
            selected={kind === 'structured_notes'}
            onClick={() => setKind('structured_notes')}
            icon={<Ic.list size={16} />}
            title="Structured Notes"
            sub="Exhaustive study cards · stacked formulas, benchmarks & zero fluff."
            time="~45 seconds"
          />
          <KindCard
            kind="mcq"
            selected={kind === 'mcq'}
            onClick={() => setKind('mcq')}
            icon={<Ic.check size={16} />}
            title="Solved MCQs / PYQ"
            sub="Every question with options, answer key, derivations & traps."
            time="~45 seconds"
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

        {/* Optional PDF features — all start OFF (no extra Claude tokens,
            no new failure modes). Each toggle adds one piece of content to
            the resulting PDF; cache key includes the feature set, so the
            same URL with different toggles caches separately. */}
        <label
          style={{
            fontSize: 12.5,
            fontWeight: 500,
            color: 'var(--c-ink-2)',
            marginBottom: 8,
            display: 'block',
          }}
        >
          Optional features <span style={{ color: 'var(--c-ink-3)', fontWeight: 400 }}>(all off by default)</span>
        </label>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 28 }}>
          {FEATURE_TILES.map((t) => (
            <FeatureTile
              key={t.flag}
              enabled={features.has(t.flag)}
              onToggle={() => toggleFeature(t.flag)}
              title={t.title}
              sub={t.sub}
            />
          ))}
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
            kind === 'book'
              ? (me?.free_books_left ?? 0)
              : (me?.free_cheatsheets_left ?? 0);
          const cost = preview.cost_paise?.[kind as 'cheatsheet' | 'book'] ?? preview.cost_paise?.cheatsheet ?? 0;
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
              if (submitting) return true;
              if (mode === 'playlist') {
                return !PLAYLIST_RE.test(url.trim());
              }
              if (!valid || previewLoading || !!previewError || !preview) {
                return true;
              }
              const freeLeft =
                kind === 'book'
                  ? (me?.free_books_left ?? 0)
                  : (me?.free_cheatsheets_left ?? 0);
              const cost = preview.cost_paise?.[kind as 'cheatsheet' | 'book'] ?? preview.cost_paise?.cheatsheet ?? 0;
              const walletPaise = me?.wallet_balance_paise ?? 0;
              return freeLeft === 0 && walletPaise < cost;
            })()}
            onClick={submit}
          >
            {submitting ? 'Starting…' : mode === 'playlist' ? 'Extract Playlist' : 'Generate now'}
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

function FeatureTile({
  enabled,
  onToggle,
  title,
  sub,
}: {
  enabled: boolean;
  onToggle: () => void;
  title: string;
  sub: string;
}) {
  return (
    <button
      onClick={onToggle}
      aria-pressed={enabled}
      style={{
        padding: '12px 14px',
        borderRadius: 10,
        border: `1.5px solid ${enabled ? 'var(--c-accent)' : 'var(--c-line-2)'}`,
        background: enabled ? 'var(--c-accent-2)' : 'var(--c-surface)',
        textAlign: 'left',
        cursor: 'pointer',
        fontFamily: 'inherit',
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
      }}
    >
      {/* Switch-style indicator — mirrors KindCard's circle but rectangular
          so toggles read as on/off and selections read as picks. */}
      <div
        style={{
          marginTop: 2,
          flex: 'none',
          width: 26,
          height: 16,
          borderRadius: 8,
          background: enabled ? 'var(--c-accent)' : 'var(--c-line-2)',
          position: 'relative',
          transition: 'background 120ms',
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 2,
            left: enabled ? 12 : 2,
            width: 12,
            height: 12,
            borderRadius: '50%',
            background: '#fff',
            transition: 'left 120ms',
          }}
        />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 13.5,
            fontWeight: 600,
            color: enabled ? 'var(--c-accent-ink)' : 'var(--c-ink)',
            marginBottom: 2,
          }}
        >
          {title}
        </div>
        <div
          style={{
            fontSize: 11.5,
            color: enabled ? 'var(--c-accent-ink)' : 'var(--c-ink-3)',
            lineHeight: 1.4,
            opacity: enabled ? 0.85 : 1,
          }}
        >
          {sub}
        </div>
      </div>
    </button>
  );
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
