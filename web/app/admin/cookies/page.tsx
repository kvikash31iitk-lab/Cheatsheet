'use client';

import { useEffect, useState } from 'react';
import {
  AdminShell,
  PageHeader,
  Section,
  Textarea,
} from '@/components/admin-shell';
import { Btn, Tag } from '@/components/ui';
import { adminApi, type AdminCookiesStatus, type AdminStorage } from '@/lib/admin-api';

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export default function AdminCookiesPage() {
  const [status, setStatus] = useState<AdminCookiesStatus | null>(null);
  const [storage, setStorage] = useState<AdminStorage | null>(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function load() {
    try {
      const [s, st] = await Promise.all([
        adminApi.cookiesStatus(),
        adminApi.storage(),
      ]);
      setStatus(s);
      setStorage(st);
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function upload() {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const r = await adminApi.uploadCookies(text);
      setSuccess(`Saved ${fmtBytes(r.bytes)} to ${r.path}`);
      setText('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AdminShell>
      <PageHeader eyebrow="ADMIN · OPS" title="yt-dlp cookies & storage" />

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
      {success && (
        <div
          style={{
            background: 'var(--c-mint-bg)',
            color: 'var(--c-mint)',
            padding: 12,
            borderRadius: 8,
            fontSize: 13,
            marginBottom: 16,
          }}
        >
          {success}
        </div>
      )}

      <Section
        title="Current cookies file"
        description="Used by yt-dlp to bypass YouTube anti-bot. Re-upload when it stops working."
        right={
          status?.exists ? (
            <Tag tone="mint">present</Tag>
          ) : (
            <Tag tone="error">missing</Tag>
          )
        }
      >
        {status?.exists ? (
          <div style={{ fontSize: 13 }}>
            <Row label="Path">
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                {status.path}
              </span>
            </Row>
            <Row label="Size">{fmtBytes(status.size_bytes)}</Row>
            <Row label="Last modified">
              {status.modified_at.slice(0, 16).replace('T', ' ')}
            </Row>
          </div>
        ) : (
          <div style={{ color: 'var(--c-ink-3)', fontSize: 13 }}>
            No cookies file found. Upload one below.
          </div>
        )}
      </Section>

      <Section
        title="Replace cookies"
        description="Paste the full Netscape cookies.txt. Must start with `# Netscape HTTP Cookie File`."
      >
        <Textarea
          label="COOKIES.TXT CONTENT"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="# Netscape HTTP Cookie File..."
          style={{ minHeight: 200, fontFamily: 'var(--font-mono)', fontSize: 11.5 }}
        />
        <Btn variant="primary" disabled={busy || !text.trim()} onClick={upload}>
          {busy ? 'Uploading…' : 'Upload & activate'}
        </Btn>
      </Section>

      {storage && (
        <Section title="Disk & DB usage">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
            <div>
              <h4
                style={{
                  fontSize: 12,
                  color: 'var(--c-ink-3)',
                  fontFamily: 'var(--font-mono)',
                  letterSpacing: '.08em',
                  margin: '0 0 8px',
                }}
              >
                DISK
              </h4>
              <Row label="Total">{fmtBytes(storage.disk.total_bytes)}</Row>
              <Row label="Used">{fmtBytes(storage.disk.used_bytes)}</Row>
              <Row label="Free">{fmtBytes(storage.disk.free_bytes)}</Row>
              <Row label="web_work/">{fmtBytes(storage.disk.work_dir_bytes)}</Row>
            </div>
            <div>
              <h4
                style={{
                  fontSize: 12,
                  color: 'var(--c-ink-3)',
                  fontFamily: 'var(--font-mono)',
                  letterSpacing: '.08em',
                  margin: '0 0 8px',
                }}
              >
                DB
              </h4>
              <Row label="users">{storage.rows.users.toLocaleString()}</Row>
              <Row label="generations">{storage.rows.generations.toLocaleString()}</Row>
              <Row label="transactions">{storage.rows.transactions.toLocaleString()}</Row>
              <Row label="audit_log">{storage.rows.audit_log.toLocaleString()}</Row>
            </div>
          </div>
        </Section>
      )}
    </AdminShell>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        padding: '6px 0',
        borderBottom: '1px solid var(--c-line)',
        fontSize: 13,
      }}
    >
      <span style={{ color: 'var(--c-ink-3)' }}>{label}</span>
      <span style={{ fontFamily: 'var(--font-mono)' }}>{children}</span>
    </div>
  );
}
