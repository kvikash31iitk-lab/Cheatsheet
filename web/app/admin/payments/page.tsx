'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { AdminShell, PageHeader, Section } from '@/components/admin-shell';
import { Tag } from '@/components/ui';
import { adminApi, type AdminPayment } from '@/lib/admin-api';

function rupees(paise: number): string {
  return `₹${(paise / 100).toFixed(2)}`;
}

export default function AdminPaymentsPage() {
  const [items, setItems] = useState<AdminPayment[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    adminApi.failedPayments().then(setItems).catch((e) => setError(String(e)));
  }, []);

  return (
    <AdminShell>
      <PageHeader
        eyebrow="ADMIN · PAYMENTS"
        title="Pending / failed top-ups"
      />
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
      <Section
        title={`Last ${items.length} non-success top-ups`}
        description="Pending = order created but user never paid. Failed = payment signature mismatch or webhook fail."
      >
        {items.length === 0 ? (
          <div style={{ color: 'var(--c-ink-3)', fontSize: 13 }}>
            No pending or failed top-ups.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
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
                  <th style={{ padding: '8px 12px' }}>WHEN</th>
                  <th style={{ padding: '8px 12px' }}>USER</th>
                  <th style={{ padding: '8px 12px' }}>AMOUNT</th>
                  <th style={{ padding: '8px 12px' }}>STATUS</th>
                  <th style={{ padding: '8px 12px' }}>ORDER</th>
                </tr>
              </thead>
              <tbody>
                {items.map((p) => (
                  <tr key={p.id} style={{ borderTop: '1px solid var(--c-line)' }}>
                    <td
                      style={{
                        padding: '10px 12px',
                        fontFamily: 'var(--font-mono)',
                        fontSize: 11.5,
                        color: 'var(--c-ink-3)',
                      }}
                    >
                      {p.created_at?.slice(5, 16).replace('T', ' ')}
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <Link
                        href={`/admin/users/${p.user_id}`}
                        style={{ color: 'var(--c-ink)', textDecoration: 'none' }}
                      >
                        {p.user_email}
                      </Link>
                    </td>
                    <td
                      style={{
                        padding: '10px 12px',
                        fontFamily: 'var(--font-mono)',
                      }}
                    >
                      {rupees(p.amount_paise)}
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <Tag tone={p.status === 'failed' ? 'error' : 'gold'}>
                        {p.status}
                      </Tag>
                    </td>
                    <td
                      style={{
                        padding: '10px 12px',
                        fontFamily: 'var(--font-mono)',
                        fontSize: 11,
                        color: 'var(--c-ink-3)',
                      }}
                    >
                      {p.razorpay_order_id ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </AdminShell>
  );
}
