'use client';

import { useEffect, useState } from 'react';
import { AdminShell, PageHeader, Section } from '@/components/admin-shell';
import { Tag } from '@/components/ui';
import { adminApi, type AdminAuditEntry } from '@/lib/admin-api';

export default function AdminAuditPage() {
  const [entries, setEntries] = useState<AdminAuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    adminApi
      .audit(300, 0)
      .then((r) => {
        setEntries(r.entries);
        setTotal(r.total);
      })
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <AdminShell>
      <PageHeader eyebrow="ADMIN · AUDIT" title={`${total} actions`} />
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
        title="Recent admin actions"
        description="Append-only log. Every state-changing endpoint writes one row."
      >
        {entries.length === 0 ? (
          <div style={{ color: 'var(--c-ink-3)', fontSize: 13 }}>None yet.</div>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {entries.map((a) => (
              <li
                key={a.id}
                style={{
                  padding: '10px 0',
                  borderBottom: '1px solid var(--c-line)',
                  fontSize: 13,
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    marginBottom: 4,
                  }}
                >
                  <Tag tone="neutral">{a.action}</Tag>
                  <span style={{ color: 'var(--c-ink-3)' }}>
                    by <strong style={{ color: 'var(--c-ink-2)' }}>{a.admin_email}</strong>
                  </span>
                  <span
                    style={{
                      marginLeft: 'auto',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 11.5,
                      color: 'var(--c-ink-3)',
                    }}
                  >
                    {a.created_at?.slice(0, 16).replace('T', ' ')}
                  </span>
                </div>
                {a.target_type && (
                  <div
                    style={{
                      fontSize: 11.5,
                      color: 'var(--c-ink-3)',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    target: {a.target_type}
                    {a.target_id ? ` · ${a.target_id}` : ''}
                  </div>
                )}
                {a.payload && (
                  <pre
                    style={{
                      fontSize: 11,
                      color: 'var(--c-ink-3)',
                      margin: '4px 0 0',
                      whiteSpace: 'pre-wrap',
                      background: 'var(--c-surface-2)',
                      padding: 8,
                      borderRadius: 6,
                    }}
                  >
                    {JSON.stringify(a.payload, null, 2)}
                  </pre>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </AdminShell>
  );
}
