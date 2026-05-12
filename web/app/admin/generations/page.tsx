'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { AdminShell, PageHeader, Section, Select } from '@/components/admin-shell';
import { Btn, Tag } from '@/components/ui';
import { adminApi, type AdminGeneration } from '@/lib/admin-api';

function rupees(paise: number): string {
  return `₹${(paise / 100).toFixed(2)}`;
}

function statusTone(status: string) {
  return status === 'done'
    ? 'mint'
    : status === 'error'
      ? 'error'
      : status === 'running' || status === 'queued'
        ? 'gold'
        : 'neutral';
}

export default function AdminGenerationsPage() {
  const [items, setItems] = useState<AdminGeneration[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState('');
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const r = await adminApi.listGenerations(status, 100, 0);
      setItems(r.generations);
      setTotal(r.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  async function retry(id: string) {
    setRetryingId(id);
    try {
      await adminApi.retryGeneration(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRetryingId(null);
    }
  }

  return (
    <AdminShell>
      <PageHeader eyebrow="ADMIN · GENERATIONS" title={`${total} total`} />

      <Section title="Filter">
        <Select
          label="STATUS"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="">All</option>
          <option value="queued">Queued</option>
          <option value="running">Running</option>
          <option value="done">Done</option>
          <option value="error">Error</option>
        </Select>
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

      <Section title={`Generations · ${items.length}`}>
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
                <th style={{ padding: '8px 12px' }}>TITLE</th>
                <th style={{ padding: '8px 12px' }}>KIND</th>
                <th style={{ padding: '8px 12px' }}>STATUS</th>
                <th style={{ padding: '8px 12px' }}>CHARGED</th>
                <th style={{ padding: '8px 12px' }}>OUR COST</th>
                <th style={{ padding: '8px 12px' }}>ACTION</th>
              </tr>
            </thead>
            <tbody>
              {items.map((g) => (
                <tr key={g.id} style={{ borderTop: '1px solid var(--c-line)' }}>
                  <td
                    style={{
                      padding: '10px 12px',
                      whiteSpace: 'nowrap',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 11.5,
                      color: 'var(--c-ink-3)',
                    }}
                  >
                    {g.created_at?.slice(5, 16).replace('T', ' ')}
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <Link
                      href={`/admin/users/${g.user_id}`}
                      style={{ color: 'var(--c-ink)', textDecoration: 'none' }}
                    >
                      {g.user_email}
                    </Link>
                  </td>
                  <td style={{ padding: '10px 12px', maxWidth: 280 }}>
                    <div
                      style={{
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                    >
                      {g.title ?? '—'}
                    </div>
                    {g.error_message && (
                      <div
                        style={{
                          fontSize: 11,
                          color: 'var(--c-error)',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          maxWidth: 280,
                        }}
                      >
                        {g.error_message}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: '10px 12px' }}>{g.kind}</td>
                  <td style={{ padding: '10px 12px' }}>
                    <Tag tone={statusTone(g.status)}>{g.status}</Tag>
                  </td>
                  <td
                    style={{
                      padding: '10px 12px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 12,
                    }}
                  >
                    {g.was_free ? 'free' : rupees(g.cost_paise)}
                  </td>
                  <td
                    style={{
                      padding: '10px 12px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 12,
                      color: 'var(--c-ink-3)',
                    }}
                    title={`LLM ${rupees(g.llm_cost_paise)} · Whisper ${rupees(g.transcription_cost_paise)}`}
                  >
                    {rupees(g.llm_cost_paise + g.transcription_cost_paise)}
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    {(g.status === 'error' || g.status === 'done') && (
                      <Btn
                        size="sm"
                        variant="outline"
                        disabled={retryingId === g.id}
                        onClick={() => retry(g.id)}
                      >
                        {retryingId === g.id ? '...' : 'Retry'}
                      </Btn>
                    )}
                  </td>
                </tr>
              ))}
              {!items.length && (
                <tr>
                  <td
                    colSpan={8}
                    style={{
                      padding: '24px 12px',
                      textAlign: 'center',
                      color: 'var(--c-ink-3)',
                    }}
                  >
                    No generations match.
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
