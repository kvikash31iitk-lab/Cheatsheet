'use client';

import { FormEvent, Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { AppBar } from '@/components/app-bar';
import { Ic } from '@/components/icons';
import { Btn, Card, Tag } from '@/components/ui';
import {
  createNewEngineJob,
  friendlyGenerationError,
  getJob,
  type Job,
} from '@/lib/api';

const YT_RE = /^https?:\/\/(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?v=|shorts\/)|youtu\.be\/)[\w-]{11}/i;

const AUTOMATIC_FEATURES = [
  'Caption-first extraction',
  'Structured TL;DRs',
  'Self-test questions',
  'Source QR',
  'PDF quality gate',
];

export default function NewEnginePage() {
  return (
    <Suspense fallback={<NewPageShell />}>
      <NewEngineFlow />
    </Suspense>
  );
}

function NewPageShell() {
  return (
    <main style={{ minHeight: '100vh' }}>
      <AppBar />
      <div style={{ maxWidth: 920, margin: '0 auto', padding: '56px 28px' }}>
        <div style={{ color: 'var(--c-ink-3)', fontSize: 13 }}>Loading new engine…</div>
      </div>
    </main>
  );
}

function NewEngineFlow() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const jobId = searchParams?.get('job') ?? '';
  const [url, setUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      try {
        const current = await getJob(jobId);
        if (cancelled) return;
        setJob(current);
        setError(null);
        if (current.status.state === 'queued' || current.status.state === 'running') {
          timer = setTimeout(poll, 1800);
        }
      } catch (e: unknown) {
        if (!cancelled) setError(friendlyGenerationError(e));
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  const valid = YT_RE.test(url.trim());
  const active = job?.status.state === 'queued' || job?.status.state === 'running';
  const done = job?.status.state === 'done' ? job.status : null;
  const failed = job?.status.state === 'error' ? job.status : null;
  const progress = job?.status.state === 'running'
    ? Math.max(4, Math.round(job.status.progress * 100))
    : job?.status.state === 'queued'
      ? 2
      : done
        ? 100
        : 0;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!valid || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const { id } = await createNewEngineJob(url.trim());
      router.replace(`/new?job=${encodeURIComponent(id)}`);
    } catch (e: unknown) {
      setError(friendlyGenerationError(e));
      setSubmitting(false);
    }
  }

  function reset() {
    setUrl('');
    setJob(null);
    setError(null);
    setSubmitting(false);
    router.replace('/new');
  }

  return (
    <main style={{ minHeight: '100vh' }}>
      <AppBar />
      <div className="new-shell">
        <section className="new-hero">
          <div>
            <Tag tone="mint">
              <Ic.sparkle size={11} /> New quality-gated engine
            </Tag>
            <h1>Paste one link.<br />Get the finished PDF.</h1>
            <p>
              No format decisions and no optional switches. The new engine gets the
              transcript first, writes substantial study notes, validates the PDF,
              and keeps completed stages ready for retry.
            </p>
          </div>

          <div className="engine-note">
            <div className="engine-note-title">Automatic on every run</div>
            {AUTOMATIC_FEATURES.map((feature) => (
              <div className="engine-note-row" key={feature}>
                <span className="check-dot"><Ic.check size={10} /></span>
                {feature}
              </div>
            ))}
          </div>
        </section>

        <Card pad={0} style={{ overflow: 'hidden', boxShadow: '0 18px 55px rgba(28,25,22,.07)' }}>
          <div className="form-head">
            <div>
              <div className="eyebrow">YTsummary / new engine</div>
              <h2>{done ? 'Your PDF is ready.' : active ? 'Building your cheatsheet.' : 'Start with a YouTube URL.'}</h2>
            </div>
            <Tag tone={done ? 'mint' : active ? 'accent' : 'neutral'}>
              {done ? 'Complete' : active ? `${progress}%` : 'One input'}
            </Tag>
          </div>

          {!jobId && (
            <form onSubmit={submit} className="new-form">
              <label htmlFor="new-youtube-url">YouTube URL</label>
              <div className={`url-field ${url && !valid ? 'invalid' : valid ? 'valid' : ''}`}>
                <Ic.yt size={20} />
                <input
                  id="new-youtube-url"
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://youtu.be/..."
                  autoFocus
                  autoComplete="off"
                />
                {valid && <span className="valid-mark"><Ic.check size={12} /></span>}
              </div>
              {url && !valid && (
                <div className="field-error">Paste a complete public YouTube video link.</div>
              )}
              <Btn
                type="submit"
                variant="accent"
                size="xl"
                full
                disabled={!valid || submitting}
                icon={<Ic.sparkle size={15} />}
              >
                {submitting ? 'Starting engine…' : 'Generate professional PDF'}
              </Btn>
              <div className="form-foot">Usually 1–5 minutes. You can safely leave this page and return.</div>
            </form>
          )}

          {jobId && !done && !failed && (
            <div className="status-panel">
              <div className="video-line">
                {job?.meta?.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={job.meta.thumbnail_url} alt="Video thumbnail" />
                ) : (
                  <div className="thumb-placeholder"><Ic.yt size={28} /></div>
                )}
                <div>
                  <div className="video-title">{job?.meta?.title || 'Reading your video…'}</div>
                  <div className="video-sub">{job?.meta?.video_id || 'The job is queued and resumable.'}</div>
                </div>
              </div>
              <div className="progress-track" aria-label={`Generation ${progress}% complete`}>
                <div className="progress-fill" style={{ width: `${progress}%` }} />
              </div>
              <div className="progress-copy">
                <span>{job?.status.state === 'running' ? job.status.step : 'Waiting for the engine'}</span>
                <span>{progress}%</span>
              </div>
              <div className="stage-grid">
                <Stage label="Transcript" complete={progress >= 34} />
                <Stage label="Structured notes" complete={progress >= 76} />
                <Stage label="PDF + validation" complete={progress >= 96} />
              </div>
            </div>
          )}

          {done && (
            <div className="done-panel">
              <div className="done-icon"><Ic.check size={24} /></div>
              <h3>{done.meta.title || 'Professional cheatsheet'}</h3>
              <p>The artifact passed Markdown and PDF validation and is ready to use.</p>
              <div className="done-actions">
                <a href={done.pdf_url} target="_blank" rel="noopener noreferrer">
                  <Btn variant="accent" size="lg" icon={<Ic.download size={14} />}>
                    Open PDF
                  </Btn>
                </a>
                <Btn variant="secondary" size="lg" onClick={reset} icon={<Ic.refresh size={14} />}>
                  Generate another
                </Btn>
              </div>
            </div>
          )}

          {failed && (
            <div className="error-panel">
              <Tag tone="error">Generation stopped</Tag>
              <h3>That run could not finish.</h3>
              <p>{friendlyGenerationError(failed.message)}</p>
              <Btn variant="secondary" size="lg" onClick={reset} icon={<Ic.refresh size={14} />}>
                Try another link
              </Btn>
            </div>
          )}

          {error && (
            <div className="request-error">{error}</div>
          )}
        </Card>

        <div className="trust-row">
          <span><Ic.check size={11} /> Caption-first</span>
          <span><Ic.check size={11} /> Resumable stages</span>
          <span><Ic.check size={11} /> Substantial-content check</span>
          <span><Ic.check size={11} /> Validated PDF artifact</span>
        </div>
      </div>

      <style jsx>{`
        .new-shell { max-width: 920px; margin: 0 auto; padding: 54px 28px 70px; }
        .new-hero { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(240px, .75fr); gap: 56px; align-items: end; margin-bottom: 38px; }
        .new-hero h1 { font-family: var(--font-serif); font-size: clamp(42px, 6vw, 68px); font-weight: 400; line-height: .98; letter-spacing: -.035em; margin: 18px 0 18px; color: var(--c-ink); }
        .new-hero p { max-width: 620px; font-size: 15px; line-height: 1.7; color: var(--c-ink-2); margin: 0; }
        .engine-note { border-left: 1px solid var(--c-line-2); padding: 4px 0 4px 24px; }
        .engine-note-title, .eyebrow { font-family: var(--font-mono); text-transform: uppercase; letter-spacing: .09em; font-size: 10.5px; color: var(--c-ink-3); }
        .engine-note-title { margin-bottom: 12px; }
        .engine-note-row { display: flex; align-items: center; gap: 9px; color: var(--c-ink-2); font-size: 12.5px; margin: 9px 0; }
        .check-dot { width: 19px; height: 19px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; background: var(--c-mint-bg); color: var(--c-mint); }
        .form-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 26px 28px 20px; border-bottom: 1px solid var(--c-line); }
        .form-head h2 { font-family: var(--font-serif); font-size: 28px; font-weight: 400; margin: 6px 0 0; color: var(--c-ink); }
        .new-form, .status-panel, .done-panel, .error-panel { padding: 30px 28px; }
        .new-form label { display: block; font-size: 12.5px; font-weight: 600; color: var(--c-ink-2); margin-bottom: 9px; }
        .url-field { height: 58px; border: 1.5px solid var(--c-line-2); border-radius: 12px; padding: 0 16px; display: flex; align-items: center; gap: 11px; background: var(--c-bg); margin-bottom: 16px; }
        .url-field:focus-within, .url-field.valid { border-color: var(--c-accent); box-shadow: 0 0 0 3px var(--c-accent-2); }
        .url-field.invalid { border-color: var(--c-error); box-shadow: none; }
        .url-field input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; font-family: var(--font-mono); color: var(--c-ink); font-size: 13.5px; }
        .valid-mark { width: 24px; height: 24px; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; color: #fff; background: var(--c-mint); }
        .field-error { color: var(--c-error); font-size: 12px; margin: -7px 0 14px; }
        .form-foot { text-align: center; color: var(--c-ink-3); font-size: 11.5px; margin-top: 12px; }
        .video-line { display: flex; align-items: center; gap: 14px; margin-bottom: 26px; }
        .video-line img, .thumb-placeholder { width: 120px; height: 68px; border-radius: 9px; object-fit: cover; flex: none; }
        .thumb-placeholder { display: flex; align-items: center; justify-content: center; background: var(--c-surface-2); color: var(--c-accent); }
        .video-title { color: var(--c-ink); font-size: 14px; font-weight: 600; line-height: 1.4; }
        .video-sub { color: var(--c-ink-3); font-family: var(--font-mono); font-size: 11px; margin-top: 5px; }
        .progress-track { width: 100%; height: 8px; border-radius: 999px; background: var(--c-surface-2); overflow: hidden; }
        .progress-fill { height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--c-accent), var(--c-mint)); transition: width .45s ease; }
        .progress-copy { display: flex; justify-content: space-between; gap: 20px; color: var(--c-ink-2); font-size: 12px; margin-top: 9px; }
        .stage-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 25px; }
        .done-panel, .error-panel { text-align: center; padding-top: 38px; padding-bottom: 42px; }
        .done-icon { width: 58px; height: 58px; margin: 0 auto 18px; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: var(--c-mint-bg); color: var(--c-mint); }
        .done-panel h3, .error-panel h3 { font-family: var(--font-serif); font-size: 30px; font-weight: 400; margin: 0 auto 8px; max-width: 620px; }
        .done-panel p, .error-panel p { color: var(--c-ink-2); margin: 0 auto 24px; max-width: 580px; line-height: 1.6; }
        .done-actions { display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; }
        .done-actions a { text-decoration: none; }
        .request-error { margin: 0 28px 28px; padding: 12px 14px; border-radius: 9px; background: var(--c-error-bg); color: var(--c-error); font-size: 12.5px; }
        .trust-row { display: flex; justify-content: center; gap: 22px; flex-wrap: wrap; margin-top: 18px; color: var(--c-ink-3); font-size: 11px; }
        .trust-row span { display: inline-flex; align-items: center; gap: 5px; }
        @media (max-width: 720px) {
          .new-shell { padding: 36px 18px 54px; }
          .new-hero { grid-template-columns: 1fr; gap: 24px; align-items: start; }
          .new-hero h1 { font-size: 46px; }
          .engine-note { border-left: 0; border-top: 1px solid var(--c-line-2); padding: 18px 0 0; display: grid; grid-template-columns: 1fr 1fr; column-gap: 12px; }
          .engine-note-title { grid-column: 1 / -1; }
          .form-head, .new-form, .status-panel, .done-panel, .error-panel { padding-left: 20px; padding-right: 20px; }
          .stage-grid { grid-template-columns: 1fr; }
          .trust-row { justify-content: flex-start; gap: 10px 18px; }
        }
        @media (max-width: 460px) {
          .engine-note { grid-template-columns: 1fr; }
          .video-line img, .thumb-placeholder { width: 92px; height: 54px; }
          .form-head h2 { font-size: 24px; }
        }
      `}</style>
    </main>
  );
}

function Stage({ label, complete }: { label: string; complete: boolean }) {
  return (
    <div
      style={{
        border: '1px solid var(--c-line)',
        borderRadius: 9,
        padding: '10px 12px',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        color: complete ? 'var(--c-mint)' : 'var(--c-ink-3)',
        background: complete ? 'var(--c-mint-bg)' : 'var(--c-surface-2)',
        fontSize: 11.5,
      }}
    >
      <Ic.check size={11} /> {label}
    </div>
  );
}
