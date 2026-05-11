'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { AdminShell, Input, PageHeader, Section } from '@/components/admin-shell';
import { Tag } from '@/components/ui';
import { adminApi, type AdminUser } from '@/lib/admin-api';

function rupees(paise: number): string {
  return `₹${(paise / 100).toLocaleString('en-IN', {
    maximumFractionDigits: 2,
  })}`;
}

function timeAgo(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso).getTime();
  const diff = Date.now() - d;
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86_400)}d ago`;
}

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(query: string) {
    setBusy(true);
    setError(null);
    try {
      const res = await adminApi.listUsers(query, 100, 0);
      setUsers(res.users);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load('');
  }, []);

  return (
    <AdminShell>
      <PageHeader
        eyebrow="ADMIN · USERS"
        title={`${total} users total`}
      />

      <Section title="Search">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            load(q);
          }}
        >
          <Input
            label="EMAIL OR NAME"
            placeholder="kvikash31..."
            value={q}
            onChange={(e) => setQ(e.target.value)}
            hint={busy ? 'Searching…' : 'Press enter to filter.'}
          />
        </form>
      </Section>

      {error && (
        <div
          style={{
            background: 'var(--c-error-bg)',
            color: 'var(--c-error)',
            padding: 12,
            borderRadius: 8,
            fontSize: 13,
            marginBottom: 16,
          }}
        >
          {error}
        </div>
      )}

      <Section title={`Results · ${users.length}`}>
        <div style={{ overflowX: 'auto' }}>
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 13,
            }}
          >
            <thead>
              <tr
                style={{
                  textAlign: 'left',
                  fontSize: 11,
                  color: 'var(--c-ink-3)',
                  fontFamily: 'var(--font-mono)',
                  letterSpacing: '.06em',
                }}
              >
                <th style={{ padding: '8px 12px' }}>EMAIL</th>
                <th style={{ padding: '8px 12px' }}>WALLET</th>
                <th style={{ padding: '8px 12px' }}>TODAY</th>
                <th style={{ padding: '8px 12px' }}>LIFETIME</th>
                <th style={{ padding: '8px 12px' }}>FLAGS</th>
                <th style={{ padding: '8px 12px' }}>SEEN</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr
                  key={u.id}
                  style={{
                    borderTop: '1px solid var(--c-line)',
                  }}
                >
                  <td style={{ padding: '10px 12px' }}>
                    <Link
                      href={`/admin/users/${u.id}`}
                      style={{
                        color: 'var(--c-ink)',
                        textDecoration: 'none',
                        fontWeight: 500,
                      }}
                    >
                      {u.email}
                    </Link>
                    {u.name && (
                      <div style={{ fontSize: 11.5, color: 'var(--c-ink-3)' }}>
                        {u.name}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)' }}>
                    {rupees(u.wallet_balance_paise)}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)' }}>
                    {u.today_cheatsheets}c · {u.today_books}b
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)' }}>
                    {u.total_generations}
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {u.is_admin && <Tag tone="violet">admin</Tag>}
                      {u.bypass_paid && <Tag tone="mint">free</Tag>}
                      {u.is_banned && <Tag tone="error">banned</Tag>}
                      {u.daily_cheatsheets_override !== null && (
                        <Tag tone="gold">cheat ovr</Tag>
                      )}
                      {u.daily_books_override !== null && (
                        <Tag tone="gold">book ovr</Tag>
                      )}
                    </div>
                  </td>
                  <td style={{ padding: '10px 12px', fontSize: 12, color: 'var(--c-ink-3)' }}>
                    {timeAgo(u.last_seen_at)}
                  </td>
                </tr>
              ))}
              {!users.length && !busy && (
                <tr>
                  <td
                    colSpan={6}
                    style={{
                      padding: '24px 12px',
                      textAlign: 'center',
                      color: 'var(--c-ink-3)',
                      fontSize: 13,
                    }}
                  >
                    No users.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>
    </AdminShell>
  );
}
