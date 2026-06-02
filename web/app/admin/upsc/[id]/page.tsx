'use client';

import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AdminShell,
  PageHeader,
  Section,
  Select,
  Textarea,
} from '@/components/admin-shell';
import { Tag } from '@/components/ui';
import { adminApi, type UpscIssue, type UpscStatus, type UpscStyle } from '@/lib/admin-api';

const STATUS_TONE: Record<UpscStatus, 'neutral' | 'accent' | 'mint' | 'gold' | 'rose'> = {
  uploaded: 'neutral',
  extracting: 'accent',
  classifying: 'accent',
  authoring: 'accent',
  rendering: 'accent',
  preview: 'gold',
  published: 'mint',
  error: 'rose',
};

const STATUS_LABEL: Record<UpscStatus, string> = {
  uploaded: 'Queued',
  extracting: 'Extracting (OCR)...',
  classifying: 'Classifying articles...',
  authoring: 'Authoring digest...',
  rendering: 'Rendering PDF...',
  preview: 'Ready for preview',
  published: 'Published',
  error: 'Error',
};

const STYLE_LABEL: Record<UpscStyle, string> = {
  academic: 'Academic',
  dense: 'Dense',
  dense_tight: 'Dense Tight',
  coaching: 'Coaching',
  magazine: 'Magazine',
};

const IN_FLIGHT: UpscStatus[] = ['uploaded', 'extracting', 'classifying', 'authoring', 'rendering'];

type IssueWithMarkdown = UpscIssue & { markdown: string | null };

function fmt(iso: string | null | undefined): string {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function fmtDuration(secs: number | null | undefined): string {
  if (secs === null || secs === undefined) return '-';
  if (secs < 60) return `${secs.toFixed(1)}s`;
  const m = Math.floor(secs / 60);
  const s = Math.round(secs - m * 60);
  return `${m}m ${s}s`;
}

type StageTiming = { label: string; seconds: number | null };

function ProcessingTime({ issue }: { issue: IssueWithMarkdown }) {
  const stages: StageTiming[] = [
    { label: 'Extract (OCR)', seconds: issue.extract_seconds },
    { label: 'Classify', seconds: issue.classify_seconds },
    { label: 'Author', seconds: issue.author_seconds },
    { label: 'Render', seconds: issue.render_seconds },
  ];
  const total = stages.reduce((acc, s) => acc + (s.seconds ?? 0), 0);
  const recorded = stages.some((s) => s.seconds !== null && s.seconds !== undefined);
  if (!recorded) {
    return (
      <div style={{ fontSize: 13, color: 'var(--c-ink-3)' }}>
        No timing data — this issue was processed before timing was instrumented.
      </div>
    );
  }
  const max = Math.max(...stages.map((s) => s.seconds ?? 0), 1);
  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 14,
        }}
      >
        <div style={{ fontSize: 12, color: 'var(--c-ink-3)', fontFamily: 'var(--font-mono)', letterSpacing: '0.06em' }}>
          TOTAL
        </div>
        <div style={{ fontFamily: 'var(--font-serif)', fontSize: 22, color: 'var(--c-ink)' }}>
          {fmtDuration(total)}
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {stages.map((s) => {
          const ratio = (s.seconds ?? 0) / max;
          const pct = (s.seconds ?? 0) / Math.max(total, 1);
          return (
            <div key={s.label}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: 13,
                  marginBottom: 4,
                }}
              >
                <span style={{ color: 'var(--c-ink)' }}>{s.label}</span>
                <span style={{ color: 'var(--c-ink-3)' }}>
                  {fmtDuration(s.seconds)}
                  {s.seconds !== null && s.seconds !== undefined && total > 0 && (
                    <span style={{ marginLeft: 8 }}>({Math.round(pct * 100)}%)</span>
                  )}
                </span>
              </div>
              <div
                style={{
                  height: 6,
                  background: 'var(--c-line-2, #e5e1d7)',
                  borderRadius: 3,
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    height: '100%',
                    width: `${ratio * 100}%`,
                    background: 'var(--c-accent, #2a5b3a)',
                    transition: 'width 0.3s',
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

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
    ghost: {
      background: 'transparent',
      color: 'var(--c-ink-2)',
      border: '1px solid var(--c-line-2)',
    },
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
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        ...styleMap[tone],
      }}
    >
      {armed ? confirmLabel : label}
    </button>
  );
}

export default function AdminUpscDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = String(params?.id ?? '');

  const [issue, setIssue] = useState<IssueWithMarkdown | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pdfReloadKey, setPdfReloadKey] = useState(0);

  // Edit state — kept separate from `issue` so cancel reverts cleanly.
  const [editing, setEditing] = useState(false);
  const [draftStyle, setDraftStyle] = useState<UpscStyle>('dense_tight');
  const [draftMarkdown, setDraftMarkdown] = useState('');
  const [draftTitle, setDraftTitle] = useState('');

  const load = useCallback(() => {
    adminApi
      .getUpscIssue(id)
      .then((r) => setIssue(r))
      .catch((e) => setError(String(e instanceof Error ? e.message : e)));
  }, [id]);

  useEffect(() => {
    if (!id) return;
    load();
  }, [id, load]);

  // Auto-poll while pipeline is running.
  useEffect(() => {
    if (!issue || !IN_FLIGHT.includes(issue.status)) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [issue, load]);

  // When entering edit mode, seed drafts from current values.
  const startEditing = useCallback(() => {
    if (!issue) return;
    setDraftStyle(issue.style);
    setDraftMarkdown(issue.markdown ?? '');
    setDraftTitle(issue.title);
    setEditing(true);
  }, [issue]);

  const saveEdits = useCallback(async () => {
    if (!issue) return;
    const patch: Parameters<typeof adminApi.patchUpscIssue>[1] = {};
    if (draftTitle !== issue.title) patch.title = draftTitle;
    if (draftStyle !== issue.style) patch.style = draftStyle;
    if (draftMarkdown !== (issue.markdown ?? '')) patch.markdown = draftMarkdown;
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      return;
    }
    try {
      const updated = await adminApi.patchUpscIssue(issue.id, patch);
      setIssue(updated);
      setEditing(false);
      // Bust the iframe cache so the preview refreshes if we re-rendered.
      setPdfReloadKey((k) => k + 1);
    } catch (e: unknown) {
      setError(String(e instanceof Error ? e.message : e));
    }
  }, [issue, draftTitle, draftStyle, draftMarkdown]);

  const onReauthor = useCallback(async () => {
    if (!issue) return;
    const updated = await adminApi.reauthorUpscIssue(issue.id);
    setIssue({ ...issue, ...updated, markdown: null });
    setPdfReloadKey((k) => k + 1);
  }, [issue]);

  const onPublish = useCallback(async () => {
    if (!issue) return;
    const updated = await adminApi.publishUpscIssue(issue.id);
    setIssue((prev) => (prev ? { ...prev, ...updated } : null));
  }, [issue]);

  const onUnpublish = useCallback(async () => {
    if (!issue) return;
    const updated = await adminApi.unpublishUpscIssue(issue.id);
    setIssue((prev) => (prev ? { ...prev, ...updated } : null));
  }, [issue]);

  const onDelete = useCallback(async () => {
    if (!issue) return;
    await adminApi.deleteUpscIssue(issue.id);
    router.push('/admin/upsc');
  }, [issue, router]);

  if (error) {
    return (
      <AdminShell>
        <PageHeader eyebrow="UPSC CHEETSHEET" title="Issue" />
        <Section title="Error">
          <div style={{ color: '#b91c1c' }}>{error}</div>
          <Link
            href="/admin/upsc"
            style={{ display: 'inline-block', marginTop: 12, fontSize: 13 }}
          >
            ← Back to list
          </Link>
        </Section>
      </AdminShell>
    );
  }

  if (!issue) {
    return (
      <AdminShell>
        <PageHeader eyebrow="UPSC CHEETSHEET" title="Loading..." />
      </AdminShell>
    );
  }

  const isInFlight = IN_FLIGHT.includes(issue.status);

  return (
    <AdminShell>
      <PageHeader
        eyebrow={`UPSC CHEETSHEET · ${issue.issue_date}`}
        title={issue.title}
        right={<Tag tone={STATUS_TONE[issue.status]}>{STATUS_LABEL[issue.status]}</Tag>}
      />

      {/* error banner */}
      {issue.status === 'error' && issue.error_message && (
        <Section title="Pipeline error" description="Re-author to retry from scratch.">
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              fontSize: 12,
              fontFamily: 'var(--font-mono)',
              padding: 12,
              background: '#fef2f2',
              border: '1px solid #fecaca',
              borderRadius: 8,
              color: '#7f1d1d',
              maxHeight: 280,
              overflow: 'auto',
            }}
          >
            {issue.error_message}
          </pre>
          <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
            <ConfirmButton
              label="Re-author"
              confirmLabel="Click again to retry"
              onConfirm={onReauthor}
            />
          </div>
        </Section>
      )}

      {isInFlight && (
        <Section
          title="Pipeline running"
          description="Refreshes every 3 seconds while a stage is active. Don't close this tab."
        >
          <div
            style={{
              fontSize: 13.5,
              color: 'var(--c-ink-2)',
              padding: '12px 16px',
              background: 'var(--c-surface-2, #f5f1ea)',
              borderRadius: 8,
            }}
          >
            Currently: <strong>{STATUS_LABEL[issue.status]}</strong>
            <div style={{ fontSize: 12, color: 'var(--c-ink-3)', marginTop: 6 }}>
              Pipeline stages: extract → classify → author → render → preview
            </div>
          </div>
        </Section>
      )}

      {/* Preview + actions, only when there's something to look at */}
      {(issue.status === 'preview' || issue.status === 'published') && (
        <Section
          title="Preview"
          description="Eyeball the PDF before you publish. Anyone with the URL can download once published."
          right={
            <div style={{ display: 'flex', gap: 8 }}>
              {issue.status === 'preview' && (
                <ConfirmButton
                  label="Publish"
                  confirmLabel="Click again to confirm"
                  onConfirm={onPublish}
                />
              )}
              {issue.status === 'published' && (
                <ConfirmButton
                  label="Unpublish"
                  confirmLabel="Click again to confirm"
                  onConfirm={onUnpublish}
                  tone="ghost"
                />
              )}
              <ConfirmButton
                label="Re-author"
                confirmLabel="Click again — wipes markdown"
                onConfirm={onReauthor}
                tone="ghost"
              />
            </div>
          }
        >
          <iframe
            key={pdfReloadKey}
            src={`/api/admin/upsc/issues/${issue.id}/pdf#toolbar=0&view=FitH`}
            style={{
              width: '100%',
              height: 720,
              border: '1px solid var(--c-line)',
              borderRadius: 10,
              background: '#f9f8f4',
            }}
          />
          {issue.status === 'published' && (
            <div style={{ marginTop: 10, fontSize: 13, color: 'var(--c-ink-2)' }}>
              Public URL:{' '}
              <a
                href={`/upsc/${issue.issue_date}`}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: 'var(--c-accent, #2a5b3a)' }}
              >
                /upsc/{issue.issue_date}
              </a>
            </div>
          )}
        </Section>
      )}

      {/* Processing time */}
      {(issue.status === 'preview' ||
        issue.status === 'published' ||
        issue.status === 'error') && (
        <Section
          title="Processing time"
          description="Per-stage wall-clock duration on the pipeline worker. Watch the bars to see what to optimise."
        >
          <ProcessingTime issue={issue} />
        </Section>
      )}

      {/* Edit panel */}
      {(issue.status === 'preview' ||
        issue.status === 'published' ||
        issue.status === 'error') && (
        <Section
          title="Edit"
          description={
            editing
              ? 'Save below to apply. Markdown or style change auto-re-renders.'
              : 'Tweak the title, swap the style, hand-edit the markdown.'
          }
          right={
            !editing ? (
              <button
                type="button"
                onClick={startEditing}
                style={{
                  padding: '8px 16px',
                  fontSize: 13,
                  background: 'transparent',
                  color: 'var(--c-ink-2)',
                  border: '1px solid var(--c-line-2)',
                  borderRadius: 8,
                  cursor: 'pointer',
                }}
              >
                Edit
              </button>
            ) : (
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  type="button"
                  onClick={() => setEditing(false)}
                  style={{
                    padding: '8px 16px',
                    fontSize: 13,
                    background: 'transparent',
                    color: 'var(--c-ink-2)',
                    border: '1px solid var(--c-line-2)',
                    borderRadius: 8,
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={saveEdits}
                  style={{
                    padding: '8px 16px',
                    fontSize: 13,
                    fontWeight: 600,
                    background: 'var(--c-accent, #2a5b3a)',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 8,
                    cursor: 'pointer',
                  }}
                >
                  Save & re-render
                </button>
              </div>
            )
          }
        >
          {!editing && (
            <dl
              style={{
                display: 'grid',
                gridTemplateColumns: '180px 1fr',
                gap: '8px 24px',
                margin: 0,
                fontSize: 13.5,
              }}
            >
              <dt style={{ color: 'var(--c-ink-3)' }}>Title</dt>
              <dd style={{ margin: 0 }}>{issue.title}</dd>
              <dt style={{ color: 'var(--c-ink-3)' }}>Source</dt>
              <dd style={{ margin: 0 }}>{issue.source}</dd>
              <dt style={{ color: 'var(--c-ink-3)' }}>Style</dt>
              <dd style={{ margin: 0 }}>{STYLE_LABEL[issue.style]}</dd>
              <dt style={{ color: 'var(--c-ink-3)' }}>Articles</dt>
              <dd style={{ margin: 0 }}>{issue.article_count}</dd>
              <dt style={{ color: 'var(--c-ink-3)' }}>Created</dt>
              <dd style={{ margin: 0 }}>{fmt(issue.created_at)}</dd>
              <dt style={{ color: 'var(--c-ink-3)' }}>Published</dt>
              <dd style={{ margin: 0 }}>{fmt(issue.published_at)}</dd>
            </dl>
          )}
          {editing && (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
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
                    TITLE
                  </div>
                  <input
                    type="text"
                    value={draftTitle}
                    onChange={(e) => setDraftTitle(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '9px 12px',
                      borderRadius: 8,
                      border: '1px solid var(--c-line-2)',
                      background: 'var(--c-surface-2)',
                      fontSize: 13.5,
                      outline: 'none',
                    }}
                  />
                </label>
                <Select
                  label="RENDERER STYLE"
                  value={draftStyle}
                  onChange={(e) => setDraftStyle(e.target.value as UpscStyle)}
                >
                  {(Object.keys(STYLE_LABEL) as UpscStyle[]).map((s) => (
                    <option key={s} value={s}>
                      {STYLE_LABEL[s]}
                    </option>
                  ))}
                </Select>
              </div>
              <Textarea
                label="DIGEST MARKDOWN"
                value={draftMarkdown}
                onChange={(e) => setDraftMarkdown(e.target.value)}
                hint="Saving with markdown changed will auto-re-render the PDF."
                style={{
                  minHeight: 480,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12.5,
                  lineHeight: 1.55,
                }}
              />
            </>
          )}
        </Section>
      )}

      <Section title="Danger zone">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 13, color: 'var(--c-ink-2)' }}>
            Hard-delete this issue and all its files. Cannot be undone.
          </div>
          <ConfirmButton
            label="Delete issue"
            confirmLabel="Click again to delete"
            onConfirm={onDelete}
            tone="danger"
          />
        </div>
      </Section>

      <div style={{ marginTop: 18 }}>
        <Link href="/admin/upsc" style={{ fontSize: 13, color: 'var(--c-ink-2)' }}>
          ← Back to list
        </Link>
      </div>
    </AdminShell>
  );
}
