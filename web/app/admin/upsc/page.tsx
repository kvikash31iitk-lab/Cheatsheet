'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AdminShell, PageHeader, Section, Input, Select } from '@/components/admin-shell';
import { Tag } from '@/components/ui';
import { adminApi, type UpscIssue, type UpscStatus, type UpscStyle } from '@/lib/admin-api';

const STATUS_LABEL: Record<UpscStatus, string> = {
  uploaded: 'Queued',
  extracting: 'Extracting (OCR)',
  classifying: 'Classifying',
  authoring: 'Authoring',
  rendering: 'Rendering',
  preview: 'Preview',
  published: 'Published',
  error: 'Error',
};

const STATUS_TONE: Record<UpscStatus, 'neutral' | 'accent' | 'positive' | 'warning'> = {
  uploaded: 'neutral',
  extracting: 'accent',
  classifying: 'accent',
  authoring: 'accent',
  rendering: 'accent',
  preview: 'warning',
  published: 'positive',
  error: 'warning',
};

const STYLE_LABEL: Record<UpscStyle, string> = {
  academic: 'Academic',
  dense: 'Dense',
  dense_tight: 'Dense Tight (default)',
  coaching: 'Coaching',
  magazine: 'Magazine',
};

function formatDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

function StatusChip({ status }: { status: UpscStatus }) {
  const tone = STATUS_TONE[status];
  const palette: Record<typeof tone, { bg: string; fg: string }> = {
    neutral: { bg: 'var(--c-line-2, #e5e1d7)', fg: 'var(--c-ink-2, #444)' },
    accent: { bg: '#dbeafe', fg: '#1e3a8a' },
    positive: { bg: '#d1fae5', fg: '#065f46' },
    warning: { bg: '#fef3c7', fg: '#92400e' },
  };
  const c = palette[tone];
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 9px',
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 600,
        background: c.bg,
        color: c.fg,
        letterSpacing: '0.02em',
      }}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

function UploadForm({ onUploaded }: { onUploaded: () => void }) {
  const [issueDate, setIssueDate] = useState(() => {
    const today = new Date();
    return today.toISOString().slice(0, 10);
  });
  const [source, setSource] = useState('Indian Express');
  const [title, setTitle] = useState('');
  const [style, setStyle] = useState<UpscStyle>('dense_tight');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const submit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!file) {
        setErr('Pick a PDF file first.');
        return;
      }
      setBusy(true);
      setErr(null);
      try {
        const fd = new FormData();
        fd.append('pdf', file);
        fd.append('issue_date', issueDate);
        fd.append('source', source);
        if (title) fd.append('title', title);
        fd.append('style', style);
        await adminApi.uploadUpscIssue(fd);
        setFile(null);
        setTitle('');
        if (fileRef.current) fileRef.current.value = '';
        onUploaded();
      } catch (e: unknown) {
        setErr(String(e instanceof Error ? e.message : e));
      } finally {
        setBusy(false);
      }
    },
    [file, issueDate, source, title, style, onUploaded],
  );

  return (
    <form onSubmit={submit}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <Input
          label="ISSUE DATE"
          type="date"
          value={issueDate}
          onChange={(e) => setIssueDate(e.target.value)}
          required
        />
        <Input
          label="SOURCE NEWSPAPER"
          type="text"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="Indian Express"
          required
        />
      </div>
      <Input
        label="TITLE (OPTIONAL)"
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Defaults to e.g. 'UPSC Cheetsheet - 01 June 2026'"
      />
      <Select
        label="RENDERER STYLE"
        value={style}
        onChange={(e) => setStyle(e.target.value as UpscStyle)}
      >
        {(Object.keys(STYLE_LABEL) as UpscStyle[]).map((s) => (
          <option key={s} value={s}>
            {STYLE_LABEL[s]}
          </option>
        ))}
      </Select>
      <label style={{ display: 'block', marginBottom: 12 }}>
        <div
          style={{
            fontSize: 11,
            color: 'var(--c-ink-3)',
            fontFamily: 'var(--font-mono)',
            letterSpacing: '.06em',
            marginBottom: 5,
          }}
        >
          NEWSPAPER PDF
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          required
          style={{ width: '100%', fontSize: 13 }}
        />
        <div style={{ fontSize: 11, color: 'var(--c-ink-3)', marginTop: 4 }}>
          Drop today&apos;s e-paper here. Pipeline extracts -&gt; classifies -&gt; authors
          -&gt; renders. Takes 5-10 minutes; refresh the list to watch progress.
        </div>
      </label>
      {err && (
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
          {err}
        </div>
      )}
      <button
        type="submit"
        disabled={busy || !file}
        style={{
          padding: '9px 18px',
          fontSize: 13.5,
          fontWeight: 600,
          background: busy || !file ? 'var(--c-line-2)' : 'var(--c-accent, #2a5b3a)',
          color: busy || !file ? 'var(--c-ink-3)' : '#fff',
          border: 'none',
          borderRadius: 8,
          cursor: busy || !file ? 'not-allowed' : 'pointer',
        }}
      >
        {busy ? 'Uploading...' : 'Upload + process'}
      </button>
    </form>
  );
}

export default function AdminUpscPage() {
  const [issues, setIssues] = useState<UpscIssue[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    adminApi
      .listUpscIssues(30, 0)
      .then((r) => setIssues(r.issues))
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000); // poll while pipelines run
    return () => clearInterval(t);
  }, [refresh]);

  const inflight = useMemo(
    () =>
      issues?.some((i) =>
        ['uploaded', 'extracting', 'classifying', 'authoring', 'rendering'].includes(i.status),
      ) ?? false,
    [issues],
  );

  return (
    <AdminShell>
      <PageHeader
        eyebrow="UPSC CHEETSHEET"
        title="Daily digest"
        right={
          inflight ? (
            <Tag tone="accent">processing...</Tag>
          ) : (
            <Tag tone="neutral">idle</Tag>
          )
        }
      />

      <Section
        title="Upload today's newspaper"
        description="Drop the e-paper PDF. Pipeline runs in the background; refresh below to track progress."
      >
        <UploadForm onUploaded={refresh} />
      </Section>

      <Section
        title="Issues"
        description="Newest first. Click any row to preview, edit, publish."
      >
        {error && (
          <div style={{ color: 'var(--c-error, #b91c1c)' }}>{error}</div>
        )}
        {!error && issues === null && (
          <div style={{ color: 'var(--c-ink-3)' }}>Loading...</div>
        )}
        {!error && issues !== null && issues.length === 0 && (
          <div style={{ color: 'var(--c-ink-3)', padding: 20, textAlign: 'center' }}>
            No issues yet. Upload one above to get started.
          </div>
        )}
        {issues && issues.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '140px 1fr 110px 110px 70px 90px',
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
              <div>TITLE / SOURCE</div>
              <div>STATUS</div>
              <div>STYLE</div>
              <div style={{ textAlign: 'right' }}>ARTICLES</div>
              <div style={{ textAlign: 'right' }}>TIME</div>
            </div>
            {issues.map((i) => (
              <Link
                key={i.id}
                href={`/admin/upsc/${i.id}`}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '140px 1fr 110px 110px 70px 90px',
                  gap: 12,
                  padding: '12px',
                  alignItems: 'center',
                  textDecoration: 'none',
                  color: 'var(--c-ink)',
                  borderBottom: '1px solid var(--c-line)',
                  fontSize: 13.5,
                }}
              >
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                  {formatDate(i.issue_date)}
                </div>
                <div>
                  <div style={{ fontWeight: 500 }}>{i.title}</div>
                  <div style={{ fontSize: 12, color: 'var(--c-ink-3)' }}>
                    {i.source}
                  </div>
                </div>
                <div>
                  <StatusChip status={i.status} />
                </div>
                <div style={{ fontSize: 12, color: 'var(--c-ink-2)' }}>
                  {STYLE_LABEL[i.style].replace(' (default)', '')}
                </div>
                <div
                  style={{
                    textAlign: 'right',
                    fontFamily: 'var(--font-serif)',
                    fontSize: 18,
                    color: 'var(--c-ink-2)',
                  }}
                >
                  {i.article_count || '-'}
                </div>
                <div
                  style={{
                    textAlign: 'right',
                    fontSize: 12,
                    color: 'var(--c-ink-3)',
                    fontFamily: 'var(--font-mono)',
                  }}
                >
                  {(() => {
                    const total =
                      (i.extract_seconds ?? 0) +
                      (i.classify_seconds ?? 0) +
                      (i.author_seconds ?? 0) +
                      (i.render_seconds ?? 0);
                    if (total <= 0) return '-';
                    if (total < 60) return `${total.toFixed(0)}s`;
                    return `${Math.round(total / 60)}m`;
                  })()}
                </div>
              </Link>
            ))}
          </div>
        )}
      </Section>
    </AdminShell>
  );
}
