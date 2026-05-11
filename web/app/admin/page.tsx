'use client';

import { useEffect, useState } from 'react';
import { AdminShell, PageHeader, Section } from '@/components/admin-shell';
import { Tag } from '@/components/ui';
import { adminApi, type AdminOverview } from '@/lib/admin-api';

function rupees(paise: number): string {
  return `₹${(paise / 100).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div
      style={{
        background: 'var(--c-surface)',
        border: '1px solid var(--c-line)',
        borderRadius: 12,
        padding: 18,
      }}
    >
      <div
        style={{
          fontSize: 11,
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
          fontFamily: 'var(--font-serif)',
          fontSize: 30,
          lineHeight: 1,
          fontStyle: 'italic',
          letterSpacing: '-0.02em',
          color: 'var(--c-ink)',
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 12, color: 'var(--c-ink-3)', marginTop: 6 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

export default function AdminOverviewPage() {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    adminApi.overview().then(setData).catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <AdminShell>
        <PageHeader eyebrow="ADMIN" title="Overview" />
        <Section title="Error">
          <div style={{ color: 'var(--c-error)' }}>{error}</div>
        </Section>
      </AdminShell>
    );
  }
  if (!data) {
    return (
      <AdminShell>
        <PageHeader eyebrow="ADMIN" title="Overview" />
        <div style={{ color: 'var(--c-ink-3)' }}>Loading…</div>
      </AdminShell>
    );
  }

  const maxBar = Math.max(
    1,
    ...data.daily_series.map((d) => d.cheatsheet + d.book),
  );

  return (
    <AdminShell>
      <PageHeader
        eyebrow="ADMIN"
        title="What's happening today"
        right={
          data.generations.running > 0 ? (
            <Tag tone="gold">{data.generations.running} running</Tag>
          ) : null
        }
      />

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 12,
          marginBottom: 20,
        }}
      >
        <Stat
          label="USERS"
          value={String(data.users.total)}
          sub={`+${data.users.today} today · +${data.users.week} this week`}
        />
        <Stat
          label="GENERATIONS TODAY"
          value={String(data.generations.today)}
          sub={`${data.generations.week} this week · ${data.generations.failed_week} failed`}
        />
        <Stat
          label="REVENUE (WEEK)"
          value={rupees(data.revenue_paise.week)}
          sub={`Today ${rupees(data.revenue_paise.today)} · Month ${rupees(data.revenue_paise.month)}`}
        />
        <Stat
          label="WALLET OUTSTANDING"
          value={rupees(data.wallet_outstanding_paise)}
          sub="Across all users"
        />
      </div>

      <Section
        title="Generations · last 30 days"
        description={`Total cheats vs books per day. Tallest bar = ${maxBar}.`}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-end',
            gap: 3,
            height: 160,
            paddingTop: 8,
          }}
        >
          {data.daily_series.map((d) => {
            const total = d.cheatsheet + d.book;
            const h = (total / maxBar) * 140;
            const ch = total ? (d.cheatsheet / total) * h : 0;
            const bk = total ? (d.book / total) * h : 0;
            return (
              <div
                key={d.date}
                title={`${d.date} · ${d.cheatsheet} cheats · ${d.book} books`}
                style={{
                  flex: 1,
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'flex-end',
                  alignItems: 'center',
                  gap: 1,
                }}
              >
                <div
                  style={{
                    width: '100%',
                    height: bk,
                    background: 'var(--c-violet)',
                    borderTopLeftRadius: 3,
                    borderTopRightRadius: 3,
                  }}
                />
                <div
                  style={{
                    width: '100%',
                    height: ch,
                    background: 'var(--c-accent)',
                    borderTopLeftRadius: bk ? 0 : 3,
                    borderTopRightRadius: bk ? 0 : 3,
                  }}
                />
              </div>
            );
          })}
        </div>
        <div
          style={{
            display: 'flex',
            gap: 16,
            marginTop: 12,
            fontSize: 11,
            color: 'var(--c-ink-3)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          <span>
            <span
              style={{
                display: 'inline-block',
                width: 10,
                height: 10,
                background: 'var(--c-accent)',
                borderRadius: 2,
                marginRight: 5,
                verticalAlign: 'middle',
              }}
            />
            CHEATSHEET
          </span>
          <span>
            <span
              style={{
                display: 'inline-block',
                width: 10,
                height: 10,
                background: 'var(--c-violet)',
                borderRadius: 2,
                marginRight: 5,
                verticalAlign: 'middle',
              }}
            />
            BOOK
          </span>
        </div>
      </Section>
    </AdminShell>
  );
}
