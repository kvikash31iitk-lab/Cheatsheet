'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { AppBar } from '@/components/app-bar';
import { Btn, Tag } from '@/components/ui';
import { Ic } from '@/components/icons';
import { createJob, type JobKind } from '@/lib/api';

const YT_RE = /^https?:\/\/(www\.)?(youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/)[\w-]{11}/;

export default function GeneratePage() {
  const router = useRouter();
  const [url, setUrl] = useState('');
  const [kind, setKind] = useState<JobKind>('cheatsheet');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = YT_RE.test(url);

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
          {valid && (
            <Tag tone="mint">
              <Ic.check size={10} /> Valid
            </Tag>
          )}
          {url && !valid && <Tag tone="error">Invalid URL</Tag>}
        </div>

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

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Btn
            variant="accent"
            size="lg"
            icon={<Ic.sparkle size={14} />}
            disabled={!valid || submitting}
            onClick={submit}
          >
            {submitting ? 'Starting…' : 'Generate now'}
          </Btn>
        </div>
      </div>
    </main>
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
