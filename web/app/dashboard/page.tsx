'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import { AppBar } from '@/components/app-bar';
import { Btn, Tag } from '@/components/ui';
import { Ic } from '@/components/icons';
import { getMe, getLibrary, type Me, type Job } from '@/lib/api';

export default function DashboardPage() {
  const { data: session } = useSession();
  const [me, setMe] = useState<Me | null>(null);
  const [items, setItems] = useState<Job[] | null>(null);

  useEffect(() => {
    getMe().then(setMe).catch(() => {});
    getLibrary().then(setItems).catch(() => {});
  }, []);

  const stats = useMemo(() => {
    if (!items) return { total: 0, cheats: 0, books: 0, doneToday: 0 };
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    let total = 0;
    let cheats = 0;
    let books = 0;
    let doneToday = 0;
    for (const j of items) {
      total++;
      if (j.kind === 'cheatsheet') cheats++;
      if (j.kind === 'book') books++;
      if (
        j.status.state === 'done' &&
        j.created_at &&
        new Date(j.created_at).getTime() >= todayStart.getTime()
      ) {
        doneToday++;
      }
    }
    return { total, cheats, books, doneToday };
  }, [items]);

  const greeting = useMemo(() => {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    return 'Good evening';
  }, []);

  const firstName = session?.user?.name?.split(' ')[0] ?? '';

  return (
    <main style={{ minHeight: '100vh' }}>
      <AppBar />

      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          padding: '24px 32px 20px',
          borderBottom: '1px solid var(--c-line)',
          maxWidth: 1200,
          margin: '0 auto',
          width: '100%',
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
            }}
          >
            HOME ·{' '}
            {new Date()
              .toLocaleDateString('en-US', { weekday: 'long' })
              .toUpperCase()}
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
            {greeting}{firstName ? `, ${firstName}` : ''}.
          </h1>
          <div style={{ fontSize: 13.5, color: 'var(--c-ink-2)', marginTop: 4 }}>
            {me
              ? `${me.free_cheatsheets_left} of ${me.free_cheatsheets_per_day} free cheatsheets and ${me.free_books_left} of ${me.free_books_per_day} book notes left today.`
              : 'Loading…'}
          </div>
        </div>
        <Link href="/generate" style={{ textDecoration: 'none' }}>
          <Btn variant="primary" size="md" icon={<Ic.plus size={13} />}>
            New generation
          </Btn>
        </Link>
      </header>

      <div style={{ padding: 32, maxWidth: 1200, margin: '0 auto' }}>
        {/* Stats row */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 14,
            marginBottom: 14,
          }}
        >
          <StatCard
            label="WALLET"
            value={`₹${((me?.wallet_balance_paise ?? 0) / 100).toFixed(2)}`}
            hint={(me?.wallet_balance_paise ?? 0) > 0 ? 'No daily cap' : 'Top up at /wallet'}
            accent={(me?.wallet_balance_paise ?? 0) > 0 ? 'var(--c-mint)' : undefined}
          />
          <StatCard
            label="FREE TODAY"
            value={`${me?.free_cheatsheets_left ?? 0}/${me?.free_cheatsheets_per_day ?? 3}`}
            sub="cheats"
            hint="Resets at IST midnight"
          />
          <StatCard
            label="FREE TODAY"
            value={`${me?.free_books_left ?? 0}/${me?.free_books_per_day ?? 1}`}
            sub="books"
            hint="Resets at IST midnight"
          />
          <StatCard
            label="GENERATED"
            value={String(stats.total)}
            sub="all time"
            hint={`${stats.cheats} cheat · ${stats.books} book`}
          />
        </div>

        {/* Quick generate + free quota */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1.6fr 1fr',
            gap: 14,
            marginBottom: 14,
          }}
        >
          <QuickGenerate />
          <FreeQuotaCard me={me} />
        </div>

        {/* Recent generations */}
        <RecentGenerations items={items?.slice(0, 5) ?? null} />
      </div>
    </main>
  );
}

function StatCard({
  label,
  value,
  sub,
  hint,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  hint?: string;
  accent?: string;
}) {
  return (
    <div
      style={{
        background: 'var(--c-surface)',
        border: '1px solid var(--c-line)',
        borderRadius: 14,
        padding: 20,
      }}
    >
      <div
        style={{
          fontSize: 11.5,
          color: 'var(--c-ink-3)',
          fontFamily: 'var(--font-mono)',
          letterSpacing: '.08em',
          marginBottom: 8,
        }}
      >
        {label}
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 6,
          marginBottom: 6,
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 38,
            lineHeight: 1,
            color: 'var(--c-ink)',
            letterSpacing: '-0.02em',
          }}
        >
          {value}
        </span>
        {sub && (
          <span style={{ fontSize: 13, color: 'var(--c-ink-3)' }}>{sub}</span>
        )}
      </div>
      {hint && (
        <div style={{ fontSize: 12, color: accent || 'var(--c-ink-3)' }}>
          {hint}
        </div>
      )}
    </div>
  );
}

function FreeQuotaCard({ me }: { me: Me | null }) {
  const cheatLeft = me?.free_cheatsheets_left ?? 0;
  const bookLeft = me?.free_books_left ?? 0;
  const cheatTotal = me?.free_cheatsheets_per_day ?? 3;
  const bookTotal = me?.free_books_per_day ?? 1;
  const used = (cheatTotal - cheatLeft) + (bookTotal - bookLeft);
  const total = cheatTotal + bookTotal;
  const pct = Math.min(100, Math.round((used / total) * 100));
  return (
    <div
      style={{
        background: 'var(--c-accent-2)',
        borderRadius: 14,
        padding: 20,
        border: '1px solid #e8c9a8',
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
        <div
          style={{
            fontSize: 11.5,
            color: 'var(--c-accent-ink)',
            fontFamily: 'var(--font-mono)',
            letterSpacing: '.08em',
          }}
        >
          FREE TODAY · LEFT
        </div>
        <Tag tone="accent" style={{ background: '#fff' }}>
          Resets at IST midnight
        </Tag>
      </div>
      <div style={{ display: 'flex', gap: 18, marginBottom: 12 }}>
        <div>
          <div
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 36,
              color: 'var(--c-accent-ink)',
              lineHeight: 1,
              fontStyle: 'italic',
            }}
          >
            {cheatLeft}
            <span
              style={{ fontSize: 18, color: 'rgba(122,52,22,.5)' }}
            >/{cheatTotal}</span>
          </div>
          <div
            style={{
              fontSize: 11.5,
              color: 'var(--c-accent-ink)',
              marginTop: 4,
            }}
          >
            Cheatsheets
          </div>
        </div>
        <div>
          <div
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 36,
              color: 'var(--c-accent-ink)',
              lineHeight: 1,
              fontStyle: 'italic',
            }}
          >
            {bookLeft}
            <span
              style={{ fontSize: 18, color: 'rgba(122,52,22,.5)' }}
            >/{bookTotal}</span>
          </div>
          <div
            style={{
              fontSize: 11.5,
              color: 'var(--c-accent-ink)',
              marginTop: 4,
            }}
          >
            Book Notes
          </div>
        </div>
      </div>
      <div
        style={{
          height: 6,
          background: 'rgba(255,255,255,.5)',
          borderRadius: 999,
          overflow: 'hidden',
          marginBottom: 8,
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background: 'var(--c-accent)',
            transition: 'width .3s ease',
          }}
        />
      </div>
      <div
        style={{
          fontSize: 11.5,
          color: 'var(--c-accent-ink)',
          opacity: 0.7,
        }}
      >
        ₹1 per 30-min cheat · ₹2 per 30-min book once past free tier
      </div>
    </div>
  );
}

function QuickGenerate() {
  const router = useRouter();
  const [url, setUrl] = useState('');
  const valid = /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)/.test(url);

  function go(kind: 'cheatsheet' | 'book') {
    if (!valid) return;
    router.push(`/generate?url=${encodeURIComponent(url)}&kind=${kind}`);
  }

  return (
    <div
      style={{
        background: 'var(--c-surface)',
        borderRadius: 14,
        padding: 20,
        border: '1px solid var(--c-line)',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 14,
        }}
      >
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--c-ink)' }}>
            Quick generate
          </div>
          <div style={{ fontSize: 12, color: 'var(--c-ink-3)' }}>
            Paste a YouTube link to get started
          </div>
        </div>
        <Tag tone="mint" style={{ fontFamily: 'var(--font-mono)' }}>
          ~30s · 1 page
        </Tag>
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: 10,
          background: 'var(--c-surface-2)',
          borderRadius: 10,
          border: `1px ${url && !valid ? 'solid var(--c-error)' : 'dashed var(--c-line-2)'}`,
          marginBottom: 12,
        }}
      >
        <Ic.yt size={16} />
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="youtube.com/watch?v=..."
          style={{
            flex: 1,
            border: 'none',
            background: 'transparent',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            outline: 'none',
            color: 'var(--c-ink)',
          }}
        />
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <Btn
          variant="primary"
          size="md"
          icon={<Ic.zap size={13} />}
          disabled={!valid}
          onClick={() => go('cheatsheet')}
        >
          Cheatsheet
        </Btn>
        <Btn
          variant="secondary"
          size="md"
          icon={<Ic.book size={13} />}
          disabled={!valid}
          onClick={() => go('book')}
        >
          Book Notes
        </Btn>
      </div>
    </div>
  );
}

function RecentGenerations({ items }: { items: Job[] | null }) {
  return (
    <div
      style={{
        background: 'var(--c-surface)',
        borderRadius: 14,
        border: '1px solid var(--c-line)',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '16px 20px',
          borderBottom: '1px solid var(--c-line)',
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--c-ink)' }}>
          Recent generations
        </div>
        <Link
          href="/library"
          style={{
            fontSize: 12,
            color: 'var(--c-accent-ink)',
            textDecoration: 'none',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
          View all <Ic.chev size={11} />
        </Link>
      </div>
      {items === null ? (
        <div style={{ padding: 24, fontSize: 13, color: 'var(--c-ink-3)' }}>
          Loading…
        </div>
      ) : items.length === 0 ? (
        <div
          style={{
            padding: 32,
            fontSize: 13,
            color: 'var(--c-ink-3)',
            textAlign: 'center',
          }}
        >
          No generations yet — try Quick Generate above.
        </div>
      ) : (
        items.map((j) => <RecentRow key={j.id} job={j} />)
      )}
    </div>
  );
}

function RecentRow({ job }: { job: Job }) {
  const meta = job.meta;
  const isFailed = job.status.state === 'error';
  return (
    <Link
      href={`/generate/${job.id}`}
      style={{ textDecoration: 'none', color: 'inherit' }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          padding: '12px 20px',
          borderBottom: '1px solid var(--c-line)',
          cursor: 'pointer',
        }}
      >
        <div
          style={{
            width: 64,
            height: 38,
            borderRadius: 6,
            background: meta?.thumbnail_url
              ? `url(${meta.thumbnail_url}) center/cover`
              : 'linear-gradient(135deg, #2a3658, #1a2440)',
            flex: 'none',
            position: 'relative',
            overflow: 'hidden',
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
                color: 'rgba(255,255,255,.7)',
              }}
            >
              <Ic.play size={12} />
            </div>
          )}
          {meta?.duration_seconds ? (
            <div
              style={{
                position: 'absolute',
                bottom: 2,
                right: 3,
                fontSize: 8.5,
                fontFamily: 'var(--font-mono)',
                color: '#fff',
                background: 'rgba(0,0,0,.7)',
                padding: '0 3px',
                borderRadius: 2,
              }}
            >
              {formatDuration(meta.duration_seconds)}
            </div>
          ) : null}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 13,
              fontWeight: 500,
              color: 'var(--c-ink)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              marginBottom: 2,
            }}
          >
            {meta?.title || (isFailed ? '(failed)' : 'Untitled')}
          </div>
          <div
            style={{
              fontSize: 11.5,
              color: 'var(--c-ink-3)',
              display: 'flex',
              gap: 8,
            }}
          >
            <span>{meta?.channel || 'YouTube'}</span>
            <span>·</span>
            <span>{relativeTime(job.created_at)}</span>
          </div>
        </div>
        <Tag tone={job.kind === 'cheatsheet' ? 'accent' : 'ink'}>
          {job.kind === 'cheatsheet' ? 'Cheatsheet' : 'Book Notes'}
        </Tag>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--c-ink-3)',
            width: 60,
            textAlign: 'right',
          }}
        >
          {isFailed ? 'failed' : job.status.state === 'done' ? 'done' : '...'}
        </div>
      </div>
    </Link>
  );
}

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0)
    return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
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
