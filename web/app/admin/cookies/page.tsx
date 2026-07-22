'use client';

import { useEffect, useRef, useState, type ChangeEvent } from 'react';
import {
  AdminShell,
  Input,
  PageHeader,
  Section,
  Textarea,
} from '@/components/admin-shell';
import { Btn, Tag } from '@/components/ui';
import {
  adminApi,
  type AdminCookiesStatus,
  type AdminStorage,
  type AdminYoutubeProbe,
  type AdminYoutubeProxyStatus,
} from '@/lib/admin-api';
import { errorMessage } from '@/lib/api';

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export default function AdminCookiesPage() {
  const [status, setStatus] = useState<AdminCookiesStatus | null>(null);
  const [storage, setStorage] = useState<AdminStorage | null>(null);
  const [proxyStatus, setProxyStatus] = useState<AdminYoutubeProxyStatus | null>(null);
  const [proxyUrl, setProxyUrl] = useState('');
  const [proxyBusy, setProxyBusy] = useState(false);
  const [text, setText] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [probeUrl, setProbeUrl] = useState('');
  const [probeBusy, setProbeBusy] = useState(false);
  const [probeResult, setProbeResult] = useState<AdminYoutubeProbe | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function load() {
    try {
      const [s, st, ps] = await Promise.all([
        adminApi.cookiesStatus(),
        adminApi.storage(),
        adminApi.youtubeProxyStatus(),
      ]);
      setStatus(s);
      setStorage(st);
      setProxyStatus(ps);
    } catch (e) {
      setError(errorMessage(e, 'Could not load YouTube access status.'));
    }
  }
  useEffect(() => {
    load();
  }, []);
  async function loadCookieFile(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) return;

    setError(null);
    setSuccess(null);
    if (file.size > 2 * 1024 * 1024) {
      setError('That file is too large. Choose a cookies.txt file under 2 MB.');
      input.value = '';
      return;
    }

    try {
      const contents = (await file.text()).replace(/^\uFEFF/, '');
      if (!contents.startsWith('# Netscape HTTP Cookie File')) {
        throw new Error(
          'Choose a Netscape cookies.txt export. The first line must be "# Netscape HTTP Cookie File".',
        );
      }
      setText(contents);
      setFileName(file.name);
    } catch (e) {
      setText('');
      setFileName(null);
      input.value = '';
      setError(errorMessage(e, 'Could not read that cookies.txt file.'));
    }
  }

  async function upload() {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const r = await adminApi.uploadCookies(text);
      setSuccess(`Cookies activated (${fmtBytes(r.bytes)}).`);
      setText('');
      setFileName(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      await load();
    } catch (e) {
      setError(errorMessage(e, 'Could not activate cookies.'));
    } finally {
      setBusy(false);
    }
  }

  async function saveProxy() {
    const value = proxyUrl.trim();
    if (!value || proxyBusy || proxyStatus?.proxy_source === 'environment') return;

    setProxyBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const next = await adminApi.saveYoutubeProxy(value);
      setProxyStatus(next);
      setProxyUrl('');
      setProbeResult(null);
      setProbeError(null);
      setSuccess('Proxy saved. Run the route test below before starting a generation.');
    } catch (e) {
      setError(errorMessage(e, 'Could not save the proxy.'));
    } finally {
      setProxyBusy(false);
    }
  }

  async function removeProxy() {
    if (proxyBusy || proxyStatus?.proxy_source !== 'admin') return;
    if (!window.confirm('Remove the admin proxy? YouTube requests will fall back to the VPS route.')) {
      return;
    }

    setProxyBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const next = await adminApi.removeYoutubeProxy();
      setProxyStatus(next);
      setProxyUrl('');
      setProbeResult(null);
      setProbeError(null);
      setSuccess('Admin proxy removed. YouTube requests now use the direct VPS route.');
    } catch (e) {
      setError(errorMessage(e, 'Could not remove the proxy.'));
    } finally {
      setProxyBusy(false);
    }
  }

  async function probeYoutube() {
    const url = probeUrl.trim();
    if (!url) return;

    setProbeBusy(true);
    setProbeResult(null);
    setProbeError(null);
    setSuccess(null);
    try {
      setProbeResult(await adminApi.probeYoutube(url));
    } catch (e) {
      setProbeError(errorMessage(e, 'Could not verify the YouTube download route.'));
    } finally {
      setProbeBusy(false);
    }
  }

  const proxyConfigured = proxyStatus?.proxy_configured ?? status?.proxy_configured ?? false;
  const environmentManaged = proxyStatus?.proxy_source === 'environment';

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
        description="Optional sign-in fallback. Cookies cannot change the VPS IP or clear 429/anti-bot blocks; configure a proxy for those."
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
            <Row label="Format">{status.valid_netscape ? 'valid' : 'invalid'}</Row>
            <Row label="YouTube cookies">{status.youtube_cookie_count} of {status.cookie_count}</Row>
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
        title="YouTube proxy"
        description="Routes YouTube traffic away from the VPS IP. The stored URL may contain credentials, so the API never returns or displays it."
        right={
          proxyStatus ? (
            <Tag tone={proxyConfigured ? 'mint' : 'error'}>
              {proxyStatus.proxy_source === 'environment'
                ? 'managed on server'
                : proxyStatus.proxy_source === 'admin'
                  ? 'admin proxy active'
                  : 'not configured'}
            </Tag>
          ) : undefined
        }
      >
        {!proxyStatus ? (
          <div style={{ color: 'var(--c-ink-3)', fontSize: 13 }}>Loading proxy status...</div>
        ) : environmentManaged ? (
          <div
            style={{
              background: 'var(--c-surface-2)',
              border: '1px solid var(--c-line)',
              borderRadius: 8,
              color: 'var(--c-ink-2)',
              fontSize: 13,
              lineHeight: 1.5,
              padding: 12,
            }}
          >
            This proxy is managed by the VPS environment. It cannot be replaced or removed here;
            update the server configuration instead. Its URL and password are never sent to this page.
          </div>
        ) : (
          <>
            <Input
              label="PROXY URL"
              type="password"
              value={proxyUrl}
              onChange={(e) => setProxyUrl(e.target.value)}
              placeholder={
                proxyStatus.proxy_source === 'admin'
                  ? 'Enter a replacement proxy URL'
                  : 'http://username:password@host:port'
              }
              autoComplete="new-password"
              spellCheck={false}
              disabled={proxyBusy}
              hint="The saved value is intentionally never shown. Saving a new URL replaces the existing admin proxy."
            />
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <Btn
                variant="primary"
                disabled={proxyBusy || !proxyUrl.trim()}
                onClick={saveProxy}
              >
                {proxyBusy ? 'Saving...' : proxyStatus.proxy_source === 'admin' ? 'Replace proxy' : 'Save proxy'}
              </Btn>
              {proxyStatus.proxy_source === 'admin' && (
                <Btn variant="secondary" disabled={proxyBusy} onClick={removeProxy}>
                  Remove admin proxy
                </Btn>
              )}
            </div>
            {proxyStatus.proxy_source === 'admin' && (
              <div style={{ color: 'var(--c-ink-3)', fontSize: 12, lineHeight: 1.45, marginTop: 10 }}>
                A stored admin proxy is active. For safety, its host, username, and password are hidden.
              </div>
            )}
          </>
        )}
      </Section>

      <Section
        title="YouTube route health"
        description="Runs a metadata-only check through the same proxy and cookie policy used by generations. It does not charge the wallet or create a generation."
        right={
          proxyStatus || status ? (
            <Tag tone={proxyConfigured ? 'mint' : 'error'}>
              {proxyConfigured ? 'proxy configured' : 'direct VPS route'}
            </Tag>
          ) : undefined
        }
      >
        <Input
          label="PUBLIC YOUTUBE URL"
          type="url"
          value={probeUrl}
          onChange={(e) => {
            setProbeUrl(e.target.value);
            setProbeResult(null);
            setProbeError(null);
          }}
          placeholder="https://www.youtube.com/watch?v=..."
          hint="Use a public video that previously failed. This does not create a generation."
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Btn
            variant="secondary"
            disabled={probeBusy || proxyBusy || !probeUrl.trim()}
            onClick={probeYoutube}
          >
            {probeBusy ? 'Testing...' : 'Test download route'}
          </Btn>
          {probeResult && <Tag tone="mint">working</Tag>}
        </div>
        {probeError && (
          <div
            style={{
              background: 'var(--c-error-bg)',
              borderRadius: 8,
              color: 'var(--c-error)',
              fontSize: 12.5,
              lineHeight: 1.5,
              marginTop: 12,
              padding: 10,
            }}
          >
            {probeError}
          </div>
        )}
        {probeResult && (
          <div style={{ fontSize: 13, marginTop: 14 }}>
            <Row label="Video">{probeResult.title}</Row>
            <Row label="Duration">{Math.max(1, Math.round(probeResult.duration_seconds / 60))} min</Row>
            <Row label="Egress">
              {probeResult.proxy_configured ? 'configured proxy' : 'direct VPS route'}
            </Row>
          </div>
        )}
      </Section>
      <Section
        title="Replace cookies"
        description="Choose a Netscape cookies.txt file or paste its full contents below."
      >
        <div style={{ marginBottom: 14 }}>
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,text/plain"
            onChange={loadCookieFile}
            aria-label="Choose cookies.txt file"
            style={{ color: 'var(--c-ink-2)', fontSize: 13 }}
          />
          {fileName ? (
            <div style={{ color: 'var(--c-mint)', fontSize: 12.5, marginTop: 8 }}>
              {fileName} loaded locally. Nothing is uploaded until you click Upload & activate.
            </div>
          ) : (
            <div style={{ color: 'var(--c-ink-3)', fontSize: 12, marginTop: 8 }}>
              Selecting a file only reads it in this browser; it is not uploaded automatically.
            </div>
          )}
        </div>
        <Textarea
          label="COOKIES.TXT CONTENT"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setFileName(null);
            if (fileInputRef.current) fileInputRef.current.value = '';
          }}
          placeholder="# Netscape HTTP Cookie File..."
          style={{ minHeight: 200, fontFamily: 'var(--font-mono)', fontSize: 11.5 }}
        />
        <Btn variant="primary" disabled={busy || !text.trim()} onClick={upload}>
          {busy ? 'Activating…' : 'Upload & activate'}
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
