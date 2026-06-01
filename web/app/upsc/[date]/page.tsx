import Link from 'next/link';
import { notFound } from 'next/navigation';
import { CSLogo, Tag } from '@/components/ui';
import { Ic } from '@/components/icons';
import { serverFetchUpscIssue } from '@/lib/upsc-api';
import type { Metadata } from 'next';

function formatDate(iso: string): string {
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

type RouteProps = {
  params: Promise<{ date: string }>;
};

export async function generateMetadata({ params }: RouteProps): Promise<Metadata> {
  const { date } = await params;
  const issue = await serverFetchUpscIssue(date);
  if (!issue) return { title: 'Issue not found · UPSC Cheetsheet' };
  const human = formatDate(issue.date);
  const desc =
    issue.summary ||
    `${issue.article_count} exam-relevant stories from ${issue.source} on ${human}.`;
  const fullTitle = `${issue.title} · ${human}`;
  const ogImage = `/api/public/upsc/thumb/${issue.date}`;
  return {
    title: fullTitle,
    description: desc,
    openGraph: {
      title: fullTitle,
      description: desc,
      type: 'article',
      siteName: 'UPSC Cheetsheet',
      images: [{ url: ogImage, width: 1240, height: 1754, alt: issue.title }],
      publishedTime: issue.published_at || undefined,
    },
    twitter: {
      card: 'summary_large_image',
      title: fullTitle,
      description: desc,
      images: [ogImage],
    },
  };
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
        <Link
          href="/upsc"
          style={{ textDecoration: 'none', color: 'var(--c-ink)', fontWeight: 500 }}
        >
          UPSC daily
        </Link>
      </nav>
    </header>
  );
}

export const dynamic = 'force-dynamic';

export default async function UpscIssuePage({ params }: RouteProps) {
  const { date } = await params;
  const issue = await serverFetchUpscIssue(date);
  if (!issue) notFound();

  const human = formatDate(issue.date);
  const pdfUrl = `/api/public/upsc/pdf/${issue.date}`;
  const thumbUrl = `/api/public/upsc/thumb/${issue.date}`;
  const issueUrl = `https://cheetsheet.tech/upsc/${issue.date}`;

  return (
    <main style={{ minHeight: '100vh', background: 'var(--c-bg, #fbf8f1)' }}>
      <NavBar />

      <article
        style={{
          maxWidth: 1180,
          margin: '0 auto',
          padding: '40px 56px 24px',
        }}
      >
        <div
          style={{
            fontSize: 13,
            color: 'var(--c-ink-3)',
            marginBottom: 16,
          }}
        >
          <Link
            href="/upsc"
            style={{ color: 'inherit', textDecoration: 'none' }}
          >
            ← Back to all issues
          </Link>
        </div>

        {/* Hero */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 320px) 1fr',
            gap: 48,
            alignItems: 'start',
            marginBottom: 40,
          }}
        >
          <div
            style={{
              aspectRatio: '1 / 1.414',
              background: 'var(--c-surface-2, #f5f1ea)',
              borderRadius: 14,
              overflow: 'hidden',
              border: '1px solid var(--c-line)',
              boxShadow: '0 24px 56px -28px rgba(0,0,0,0.22)',
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={thumbUrl}
              alt={`${issue.title} cover`}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'cover',
                display: 'block',
              }}
            />
          </div>
          <div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 18, alignItems: 'center' }}>
              <Tag tone="accent">
                <Ic.sparkle size={11} /> {issue.source}
              </Tag>
              <Tag tone="neutral">{human}</Tag>
            </div>
            <h1
              style={{
                fontFamily: 'var(--font-serif)',
                fontSize: 52,
                lineHeight: 1.05,
                letterSpacing: '-0.025em',
                color: 'var(--c-ink)',
                margin: '0 0 18px',
                fontWeight: 400,
              }}
            >
              {issue.title}
            </h1>
            {issue.summary && (
              <p
                style={{
                  fontSize: 17.5,
                  lineHeight: 1.55,
                  color: 'var(--c-ink-2)',
                  margin: '0 0 28px',
                  maxWidth: 580,
                }}
              >
                {issue.summary}
              </p>
            )}
            <div style={{ display: 'flex', gap: 12, marginBottom: 24 }}>
              <a
                href={pdfUrl}
                download={`upsc-cheetsheet-${issue.date}.pdf`}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '13px 26px',
                  borderRadius: 11,
                  background: 'var(--c-accent, #2a5b3a)',
                  color: '#fff',
                  fontSize: 15,
                  fontWeight: 500,
                  textDecoration: 'none',
                }}
              >
                Download PDF
              </a>
              <a
                href={pdfUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '13px 22px',
                  borderRadius: 11,
                  background: 'transparent',
                  color: 'var(--c-ink-2)',
                  fontSize: 15,
                  border: '1px solid var(--c-line-2)',
                  textDecoration: 'none',
                }}
              >
                Open in new tab
              </a>
            </div>
            <div
              style={{
                display: 'flex',
                gap: 32,
                fontSize: 13,
                color: 'var(--c-ink-3)',
                paddingTop: 20,
                borderTop: '1px solid var(--c-line)',
              }}
            >
              <span>
                <strong style={{ color: 'var(--c-ink)' }}>{issue.article_count}</strong>{' '}
                exam-relevant stories
              </span>
              {issue.published_at && (
                <span>
                  Published{' '}
                  {new Date(issue.published_at).toLocaleString('en-IN', {
                    day: 'numeric',
                    month: 'short',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </span>
              )}
              <span style={{ marginLeft: 'auto' }}>
                <a
                  href={`https://wa.me/?text=${encodeURIComponent(
                    `${issue.title} — ${issueUrl}`,
                  )}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: 'var(--c-ink-2)', textDecoration: 'none' }}
                >
                  Share on WhatsApp →
                </a>
              </span>
            </div>
          </div>
        </div>
      </article>

      {/* Embedded PDF */}
      <section style={{ maxWidth: 1180, margin: '0 auto', padding: '0 56px 40px' }}>
        <div
          style={{
            fontSize: 11,
            fontFamily: 'var(--font-mono)',
            color: 'var(--c-ink-3)',
            letterSpacing: '0.06em',
            marginBottom: 8,
          }}
        >
          PREVIEW
        </div>
        <iframe
          src={`${pdfUrl}#view=FitH`}
          title={issue.title}
          style={{
            width: '100%',
            height: 920,
            border: '1px solid var(--c-line)',
            borderRadius: 14,
            background: '#f9f8f4',
            boxShadow: '0 12px 36px -16px rgba(0,0,0,0.18)',
          }}
        />
      </section>

      <footer
        style={{
          padding: '40px 56px',
          borderTop: '1px solid var(--c-line)',
          marginTop: 24,
          textAlign: 'center',
          fontSize: 13,
          color: 'var(--c-ink-3)',
        }}
      >
        <div style={{ marginBottom: 8 }}>
          <Link
            href="/upsc"
            style={{ color: 'inherit', textDecoration: 'none', marginRight: 16 }}
          >
            ← All UPSC issues
          </Link>
          <Link
            href="/"
            style={{ color: 'inherit', textDecoration: 'none' }}
          >
            cheetsheet.tech →
          </Link>
        </div>
        <div>
          Analysis based on {issue.source} coverage. Not a substitute for reading
          the original article.
        </div>
      </footer>
    </main>
  );
}
