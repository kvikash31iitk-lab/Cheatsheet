'use client';

import { useEffect, useState } from 'react';
import {
  AdminShell,
  Input,
  PageHeader,
  Section,
  Select,
} from '@/components/admin-shell';
import { Btn, Tag } from '@/components/ui';
import { adminApi, type AdminBlock } from '@/lib/admin-api';

export default function AdminBlocksPage() {
  const [items, setItems] = useState<AdminBlock[]>([]);
  const [kind, setKind] = useState<'channel' | 'keyword'>('keyword');
  const [pattern, setPattern] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setItems(await adminApi.listBlocks());
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function create() {
    if (!pattern.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await adminApi.createBlock({
        kind,
        pattern: pattern.trim(),
        reason: reason.trim() || undefined,
      });
      setPattern('');
      setReason('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (!confirm('Delete this block rule?')) return;
    try {
      await adminApi.deleteBlock(id);
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <AdminShell>
      <PageHeader eyebrow="ADMIN · MODERATION" title="Block rules" />
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
        title="Add rule"
        description="`channel` = exact case-insensitive channel name match. `keyword` = case-insensitive substring in the video title."
      >
        <div style={{ display: 'grid', gridTemplateColumns: '180px 1fr 1fr', gap: 12 }}>
          <Select
            label="KIND"
            value={kind}
            onChange={(e) => setKind(e.target.value as 'channel' | 'keyword')}
          >
            <option value="keyword">keyword</option>
            <option value="channel">channel</option>
          </Select>
          <Input
            label="PATTERN"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            placeholder={kind === 'channel' ? 'Channel Name' : 'spam keyword'}
          />
          <Input
            label="REASON (OPTIONAL)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="user-facing message"
          />
        </div>
        <Btn variant="primary" disabled={busy} onClick={create}>
          {busy ? 'Adding…' : 'Add rule'}
        </Btn>
      </Section>

      <Section title={`Active rules · ${items.length}`}>
        {items.length === 0 ? (
          <div style={{ color: 'var(--c-ink-3)', fontSize: 13 }}>None.</div>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {items.map((b) => (
              <li
                key={b.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '10px 0',
                  borderBottom: '1px solid var(--c-line)',
                  fontSize: 13,
                }}
              >
                <Tag tone="neutral">{b.kind}</Tag>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{b.pattern}</span>
                {b.reason && (
                  <span style={{ color: 'var(--c-ink-3)' }}>· {b.reason}</span>
                )}
                <span
                  style={{
                    marginLeft: 'auto',
                    fontSize: 11.5,
                    color: 'var(--c-ink-3)',
                  }}
                >
                  {b.created_by ?? '—'}
                </span>
                <Btn size="sm" variant="outline" onClick={() => remove(b.id)}>
                  Delete
                </Btn>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </AdminShell>
  );
}
