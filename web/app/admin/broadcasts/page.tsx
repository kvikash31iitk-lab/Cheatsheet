'use client';

import { useEffect, useState } from 'react';
import {
  AdminShell,
  Input,
  PageHeader,
  Section,
  Textarea,
} from '@/components/admin-shell';
import { Btn, Tag } from '@/components/ui';
import { adminApi, type AdminBroadcast } from '@/lib/admin-api';

export default function AdminBroadcastsPage() {
  const [items, setItems] = useState<AdminBroadcast[]>([]);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [banner, setBanner] = useState(true);
  const [telegram, setTelegram] = useState(false);
  const [expiresHours, setExpiresHours] = useState('24');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setItems(await adminApi.listBroadcasts());
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function create() {
    if (!title.trim() || !body.trim()) return;
    const channels: Array<'banner' | 'telegram'> = [];
    if (banner) channels.push('banner');
    if (telegram) channels.push('telegram');
    if (!channels.length) {
      setError('Pick at least one channel');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await adminApi.createBroadcast({
        title: title.trim(),
        body: body.trim(),
        channels,
        expires_in_hours: expiresHours ? Number(expiresHours) : undefined,
      });
      setTitle('');
      setBody('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function deactivate(id: string) {
    try {
      await adminApi.deactivateBroadcast(id);
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <AdminShell>
      <PageHeader eyebrow="ADMIN · BROADCASTS" title="Tell everyone" />

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
        title="New broadcast"
        description="Banner shows on every page until it expires. Telegram fans out to whitelisted groups."
      >
        <Input
          label="TITLE"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Whisper backend is slow today"
        />
        <Textarea
          label="BODY"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Generations may take 2–3× longer than usual; we're on it."
        />
        <div
          style={{
            display: 'flex',
            gap: 16,
            alignItems: 'center',
            marginBottom: 12,
            fontSize: 13,
          }}
        >
          <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <input
              type="checkbox"
              checked={banner}
              onChange={(e) => setBanner(e.target.checked)}
            />
            Banner on web app
          </label>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <input
              type="checkbox"
              checked={telegram}
              onChange={(e) => setTelegram(e.target.checked)}
            />
            Telegram (whitelisted groups)
          </label>
        </div>
        <Input
          label="EXPIRES IN (HOURS)"
          type="number"
          min={1}
          value={expiresHours}
          hint="Leave 0 / empty for no expiry. Banners can also be deactivated manually below."
          onChange={(e) => setExpiresHours(e.target.value)}
        />
        <Btn variant="primary" disabled={busy} onClick={create}>
          {busy ? 'Sending…' : 'Publish'}
        </Btn>
      </Section>

      <Section title={`History · ${items.length}`}>
        {items.length === 0 ? (
          <div style={{ color: 'var(--c-ink-3)', fontSize: 13 }}>No broadcasts yet.</div>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {items.map((b) => (
              <li
                key={b.id}
                style={{
                  padding: '12px 0',
                  borderBottom: '1px solid var(--c-line)',
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
                  <strong style={{ fontSize: 14 }}>{b.title}</strong>
                  {b.active ? (
                    <Tag tone="mint">active</Tag>
                  ) : (
                    <Tag tone="neutral">off</Tag>
                  )}
                  {b.channels.map((c) => (
                    <Tag key={c} tone="neutral">
                      {c}
                    </Tag>
                  ))}
                  <span
                    style={{
                      marginLeft: 'auto',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 11.5,
                      color: 'var(--c-ink-3)',
                    }}
                  >
                    {b.created_at?.slice(0, 16).replace('T', ' ')}
                  </span>
                </div>
                <div style={{ fontSize: 13, color: 'var(--c-ink-2)' }}>{b.body}</div>
                {b.active && (
                  <div style={{ marginTop: 8 }}>
                    <Btn
                      size="sm"
                      variant="outline"
                      onClick={() => deactivate(b.id)}
                    >
                      Deactivate
                    </Btn>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </AdminShell>
  );
}
