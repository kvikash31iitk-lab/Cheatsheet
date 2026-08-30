'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { AppBar } from '@/components/app-bar';
import { Btn, Tag } from '@/components/ui';
import { Ic } from '@/components/icons';
import { friendlyGenerationError, getJob, rebuildPdf, type Job } from '@/lib/api';

export default function JobPage() {
  const params = useParams<{ jobId: string }>();
  const jobId = params?.jobId;
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function tick() {
      try {
        const j = await getJob(jobId);
        if (cancelled) return;
        setJob(j);
        if (j.status.state === 'queued' || j.status.state === 'running') {
          timer = setTimeout(tick, 1500);
        }
      } catch (e: unknown) {
        if (cancelled) return;
        setError(friendlyGenerationError(e));
        timer = setTimeout(tick, 3000);
      }
    }
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  if (error) return <ErrorView message={error} />;
  if (!job) return <LoadingSkeleton />;

  return (
    <main style={{ minHeight: '100vh', paddingBottom: 80 }}>
      <AppBar />
      <div style={{ maxWidth: 860, margin: '40px auto', padding: '0 24px' }}>
        {job.status.state === 'done' && <DoneView job={job} />}
        {job.status.state === 'error' && <ErrorView message={job.status.message} />}
        {(job.status.state === 'queued' || job.status.state === 'running') && (
          <ProgressView job={job} />
        )}
      </div>
    </main>
  );
}

function LoadingSkeleton() {
  return (
    <main style={{ minHeight: '100vh' }}>
      <AppBar />
      <div style={{ maxWidth: 760, margin: '40px auto', padding: 32 }}>
        <div style={{ fontSize: 14, color: 'var(--c-ink-3)' }}>Loading generation…</div>
      </div>
    </main>
  );
}

function ProgressView({ job }: { job: Job }) {
  const status = job.status;
  const progress = status.state === 'running' ? status.progress : 0.05;
  const step = status.state === 'running' ? status.step : 'Queued in pipeline';
  const meta = job.meta;

  return (
    <>
      <div
        style={{
          background: 'var(--c-surface)',
          border: '1px solid var(--c-line)',
          borderRadius: 14,
          padding: '40px 48px',
          marginBottom: 16,
        }}
      >
        <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
          <Tag tone="accent">Processing</Tag>
          <Tag>{job.kind === 'cheatsheet' ? 'Cheatsheet' : job.kind === 'mcq' ? 'MCQ Handbook' : 'Book Notes'}</Tag>
        </div>
        <h2
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 32,
            fontWeight: 400,
            letterSpacing: '-0.02em',
            margin: '0 0 8px',
          }}
        >
          Generating your notes…
        </h2>
        <p style={{ fontSize: 14, color: 'var(--c-ink-2)', margin: '0 0 32px' }}>
          Parsing transcript, organizing chapters, and rendering print-ready PDF.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: 12,
              color: 'var(--c-ink-3)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            <span>{Math.round(progress * 100)}% complete</span>
            <span>{step}</span>
          </div>
          <div
            style={{
              height: 6,
              background: 'rgba(255,255,255,.08)',
              borderRadius: 999,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${Math.max(4, Math.round(progress * 100))}%`,
                height: '100%',
                background: 'linear-gradient(90deg, var(--c-accent), #e8a583)',
                borderRadius: 999,
                transition: 'width .4s ease',
              }}
            />
          </div>
        </div>
      </div>
    </>
  );
}

function DoneView({ job }: { job: Job }) {
  if (job.status.state !== 'done') return null;
  const { pdf_url, markdown, meta } = job.status;
  const [rebuilding, setRebuilding] = useState(false);
  const [rebuildMsg, setRebuildMsg] = useState<string | null>(null);

  const handleRebuild = async () => {
    if (rebuilding) return;
    setRebuilding(true);
    setRebuildMsg(null);
    try {
      await rebuildPdf(job.id);
      setRebuildMsg('PDF re-compiled instantly!');
      setTimeout(() => {
        window.location.reload();
      }, 800);
    } catch (err: any) {
      setRebuildMsg(err.message || 'Failed to re-compile PDF');
      setRebuilding(false);
    }
  };

  return (
    <article
      style={{
        background: 'var(--c-surface)',
        border: '1px solid var(--c-line)',
        borderRadius: 14,
        padding: '40px 48px',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 24,
        }}
      >
        <div style={{ display: 'flex', gap: 8 }}>
          <Tag tone="mint">
            <Ic.check size={10} /> Generated
          </Tag>
          <Tag tone="accent">{job.kind === 'cheatsheet' ? 'Cheatsheet' : job.kind === 'mcq' ? 'MCQ Handbook' : 'Book Notes'}</Tag>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Btn variant="secondary" size="md" onClick={handleRebuild} disabled={rebuilding}>
            {rebuilding ? 'Re-compiling...' : '⚡ Re-compile PDF'}
          </Btn>
          <a href={pdf_url} target="_blank" rel="noopener noreferrer" style={{ textDecoration: 'none' }}>
            <Btn variant="primary" size="md" icon={<Ic.download size={13} />}>
              Download PDF
            </Btn>
          </a>
        </div>
      </div>
      {rebuildMsg && (
        <div style={{ fontSize: 12, color: 'var(--c-accent)', marginBottom: 12, textAlign: 'right' }}>
          {rebuildMsg}
        </div>
      )}

      <div
        style={{
          fontSize: 11,
          color: 'var(--c-ink-3)',
          fontFamily: 'var(--font-mono)',
          letterSpacing: '.06em',
          marginBottom: 6,
        }}
      >
        {meta.channel ? meta.channel.toUpperCase() : 'YOUTUBE'} · {formatDuration(meta.duration_seconds)}
      </div>
      <h1
        style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 36,
          fontWeight: 400,
          letterSpacing: '-0.02em',
          lineHeight: 1.1,
          margin: '0 0 24px',
          color: 'var(--c-ink)',
        }}
      >
        {meta.title}
      </h1>

      <div
        style={{
          fontSize: 14,
          lineHeight: 1.6,
          color: 'var(--c-ink-2)',
          whiteSpace: 'pre-wrap',
          fontFamily: 'var(--font-sans)',
          background: 'var(--c-surface-2)',
          padding: 20,
          borderRadius: 10,
          maxHeight: 500,
          overflow: 'auto',
        }}
      >
        {markdown}
      </div>
    </article>
  );
}

function ErrorView({ message }: { message: string }) {
  const friendlyMessage = friendlyGenerationError(message);

  return (
    <div
      style={{
        background: 'var(--c-error-bg)',
        color: 'var(--c-error)',
        borderRadius: 14,
        padding: 24,
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Generation failed</div>
      <div style={{ fontSize: 13, lineHeight: 1.5, marginBottom: 16 }}>{friendlyMessage}</div>
      <Link href="/generate" style={{ textDecoration: 'none' }}>
        <Btn variant="secondary" size="md">
          Try again
        </Btn>
      </Link>
    </div>
  );
}

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
  return `${m}:${String(sec).padStart(2, '0')}`;
}
