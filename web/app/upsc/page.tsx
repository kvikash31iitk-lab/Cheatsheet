import Link from 'next/link';
import { CSLogo, Tag } from '@/components/ui';
import { Ic } from '@/components/icons';
import { serverFetchUpscList, type UpscIssueCard } from '@/lib/upsc-api';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'UPSC Cheetsheet — Daily newspaper digest for Civil Services aspirants',
  description:
    'A free, exam-targeted summary of today\'s newspaper. Paper-wise GS tags, static linkage, real PYQs per article, and Prelims + Mains practice questions. Delivered daily.',
  openGraph: {
    title: 'UPSC Cheetsheet — Daily newspaper digest',
    description:
      'Exam-targeted summary of today\'s newspaper. GS tags, static linkage, real PYQs. Free, daily.',
    type: 'website',
    siteName: 'Cheetsheet',
  },
  twitter: { card: 'summary_large_image' },
};

export const dynamic = 'force-dynamic'; // always re-fetch — daily content

function formatDate(iso: string): string {
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

function relativeDate(iso: string): string {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const d = new Date(iso + 'T00:00:00');
  const days = Math.round((today.getTime() - d.getTime()) / 86_400_000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;
  return formatDate(iso);
}

function NavBar() {
  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '20px 56px',
        borderBottom: '1px solid var(--c-line)',
      }}
    >
      <Link href="/" style={{ textDecoration: 'none', color: 'inherit' }}>
        <CSLogo size={18} />
      </Link>
      <nav style={{ display: 'flex', gap: 28, fontSize: 13.5, color: 'var(--c-ink-2)' }}>
        <Link href="/" style={{ textDecoration: 'none', color: 'inherit' }}>
          YouTube cheatsheets
        </Link>
        <Link href="/upsc" style={{ textDecoration: 'none', color: 'var(--c-ink)', fontWeight: 500 }}>
          UPSC daily
        </Link>
      </nav>
    </header>
  );
}

function HeroCard({ issue }: { issue: UpscIssueCard }) {
  const thumbUrl = `/api/public/upsc/thumb/${issue.date}`;
  return (
    <Link
      href={`/upsc/${issue.date}`}
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 340px) 1fr',
        gap: 40,
        alignItems: 'center',
        padding: 40,
        background: 'var(--c-surface)',
        border: '1px solid var(--c-line)',
        borderRadius: 18,
        textDecoration: 'none',
        color: 'inherit',
        transition: 'border-color 0.15s, box-shadow 0.15s',
        boxShadow: '0 1px 0 rgba(0,0,0,0.02), 0 8px 32px -16px rgba(0,0,0,0.08)',
      }}
    >
      <div
        style={{
          position: 'relative',
          aspectRatio: '1 / 1.414',
          background: 'var(--c-surface-2, #f5f1ea)',
          borderRadius: 12,
          overflow: 'hidden',
          border: '1px solid var(--c-line)',
          boxShadow: '0 12px 36px -16px rgba(0,0,0,0.18)',
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={thumbUrl}
          alt={`${issue.title} cover`}
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
        />
      </div>
      <div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' }}>
          <Tag tone="accent">
            <Ic.sparkle size={11} /> {relativeDate(issue.date)}
          </Tag>
          <Tag tone="neutral">{issue.source}</Tag>
        </div>
        <h2
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 42,
            lineHeight: 1.1,
            letterSpacing: '-0.02em',
            margin: '0 0 16px',
            color: 'var(--c-ink)',
            fontWeight: 400,
          }}
        >
          {issue.title}
        </h2>
        {issue.summary && (
          <p
            style={{
              fontSize: 16,
              lineHeight: 1.6,
              color: 'var(--c-ink-2)',
              margin: '0 0 24px',
              maxWidth: 540,
            }}
          >
            {issue.summary}
          </p>
        )}
        <div style={{ display: 'flex', gap: 24, fontSize: 13, color: 'var(--c-ink-3)' }}>
          <span>
            <strong style={{ color: 'var(--c-ink)' }}>{issue.article_count}</strong> articles
          </span>
          <span>{formatDate(issue.date)}</span>
        </div>
        <div
          style={{
            marginTop: 28,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            padding: '11px 22px',
            borderRadius: 10,
            background: 'var(--c-accent, #2a5b3a)',
            color: '#fff',
            fontSize: 14,
            fontWeight: 500,
          }}
        >
          Read today&apos;s digest →
        </div>
      </div>
    </Link>
  );
}

function IssueCard({ issue }: { issue: UpscIssueCard }) {
  const thumbUrl = `/api/public/upsc/thumb/${issue.date}`;
  return (
    <Link
      href={`/upsc/${issue.date}`}
      style={{
        display: 'flex',
        flexDirection: 'column',
        textDecoration: 'none',
        color: 'inherit',
        background: 'var(--c-surface)',
        border: '1px solid var(--c-line)',
        borderRadius: 12,
        overflow: 'hidden',
        transition: 'transform 0.15s, box-shadow 0.15s',
      }}
    >
      <div
        style={{
          aspectRatio: '1 / 1.414',
          background: 'var(--c-surface-2, #f5f1ea)',
          borderBottom: '1px solid var(--c-line)',
          overflow: 'hidden',
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={thumbUrl}
          alt={`${issue.title} cover`}
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
        />
      </div>
      <div style={{ padding: 16 }}>
        <div
          style={{
            fontSize: 11.5,
            fontFamily: 'var(--font-mono)',
            color: 'var(--c-ink-3)',
            letterSpacing: '0.06em',
            marginBottom: 8,
          }}
        >
          {formatDate(issue.date).toUpperCase()}
        </div>
        <div
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 19,
            lineHeight: 1.25,
            color: 'var(--c-ink)',
            marginBottom: 8,
            letterSpacing: '-0.01em',
          }}
        >
          {issue.title}
        </div>
        <div style={{ fontSize: 12, color: 'var(--c-ink-3)' }}>
          {issue.article_count} articles · {issue.source}
        </div>
      </div>
    </Link>
  );
}

function EmptyState() {
  return (
    <div
      style={{
        textAlign: 'center',
        padding: '64px 32px',
        background: 'var(--c-surface)',
        border: '1px solid var(--c-line)',
        borderRadius: 18,
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 28,
          color: 'var(--c-ink)',
          marginBottom: 12,
          fontStyle: 'italic',
        }}
      >
        First issue lands soon.
      </div>
      <div style={{ fontSize: 15, color: 'var(--c-ink-2)', maxWidth: 480, margin: '0 auto' }}>
        We&apos;re prepping the daily UPSC newspaper digest. Each issue covers
        12-15 exam-relevant stories with paper-wise tags, static linkage, and
        verified PYQ matches.
      </div>
    </div>
  );
}

export default async function UpscLandingPage() {
  const issues = await serverFetchUpscList(24);
  const [hero, ...rest] = issues;

  return (
    <main style={{ minHeight: '100vh', background: 'var(--c-bg, #fbf8f1)' }}>
      <NavBar />

      <section
        style={{
          padding: '56px 56px 24px',
          maxWidth: 1180,
          margin: '0 auto',
          textAlign: 'center',
        }}
      >
        <Tag tone="accent" style={{ marginBottom: 18, padding: '5px 14px' }}>
          <Ic.sparkle size={11} /> New · daily UPSC digest
        </Tag>
        <h1
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 62,
            lineHeight: 1.05,
            letterSpacing: '-0.025em',
            color: 'var(--c-ink)',
            margin: '0 0 18px',
            fontWeight: 400,
          }}
        >
          Today&apos;s newspaper, <em style={{ fontStyle: 'italic' }}>UPSC-ready</em> by sunrise.
        </h1>
        <p
          style={{
            fontSize: 18,
            lineHeight: 1.55,
            color: 'var(--c-ink-2)',
            maxWidth: 640,
            margin: '0 auto 8px',
          }}
        >
          15 exam-relevant stories distilled into one tight PDF. Paper-wise GS tags,
          static linkage, two Prelims MCQs + one Mains question per article, and
          <strong> only verified PYQ citations</strong> — never LLM-fabricated.
        </p>
        <p style={{ fontSize: 14, color: 'var(--c-ink-3)', margin: 0 }}>
          Free. No login. Drop into your inbox at 7:30 AM IST.
        </p>
      </section>

      <section style={{ padding: '0 56px', maxWidth: 1180, margin: '0 auto' }}>
        {!hero && <EmptyState />}
        {hero && <HeroCard issue={hero} />}
      </section>

      {rest.length > 0 && (
        <section style={{ padding: '56px 56px', maxWidth: 1180, margin: '0 auto' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              justifyContent: 'space-between',
              marginBottom: 24,
            }}
          >
            <h2
              style={{
                fontFamily: 'var(--font-serif)',
                fontSize: 28,
                margin: 0,
                color: 'var(--c-ink)',
                fontWeight: 400,
                letterSpacing: '-0.015em',
              }}
            >
              Recent issues
            </h2>
            <div
              style={{
                fontSize: 12,
                fontFamily: 'var(--font-mono)',
                color: 'var(--c-ink-3)',
                letterSpacing: '0.06em',
              }}
            >
              {rest.length} ARCHIVED
            </div>
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
              gap: 20,
            }}
          >
            {rest.map((issue) => (
              <IssueCard key={issue.date} issue={issue} />
            ))}
          </div>
        </section>
      )}

      <footer
        style={{
          padding: '56px 56px 40px',
          borderTop: '1px solid var(--c-line)',
          marginTop: 56,
          textAlign: 'center',
          fontSize: 13,
          color: 'var(--c-ink-3)',
        }}
      >
        <div style={{ marginBottom: 8 }}>
          <Link href="/" style={{ color: 'inherit', textDecoration: 'none' }}>
            cheetsheet.tech
          </Link>
        </div>
        <div>
          Generated daily for Civil Services aspirants. Analysis based on Indian Express
          coverage; not a substitute for reading the original.
        </div>
      </footer>
    </main>
  );
}
