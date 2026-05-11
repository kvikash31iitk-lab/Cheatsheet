'use client';

import { useEffect, useState } from 'react';
import { AdminShell, Input, PageHeader, Section } from '@/components/admin-shell';
import { Btn, Tag } from '@/components/ui';
import { adminApi, type AdminPromo } from '@/lib/admin-api';

function rupees(paise: number): string {
  return `₹${(paise / 100).toFixed(2)}`;
}

export default function AdminPromosPage() {
  const [items, setItems] = useState<AdminPromo[]>([]);
  const [code, setCode] = useState('');
  const [creditRupees, setCreditRupees] = useState('100');
  const [maxRedemptions, setMaxRedemptions] = useState('0');
  const [expiresInDays, setExpiresInDays] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setItems(await adminApi.listPromos());
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function create() {
    if (!code.trim() || !creditRupees) return;
    setBusy(true);
    setError(null);
    try {
      await adminApi.createPromo({
        code: code.trim().toUpperCase(),
        credit_paise: Math.round(Number(creditRupees) * 100),
        max_redemptions: Number(maxRedemptions) || 0,
        expires_in_days: expiresInDays ? Number(expiresInDays) : undefined,
      });
      setCode('');
      setCreditRupees('100');
      setMaxRedemptions('0');
      setExpiresInDays('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function deactivate(id: string) {
    try {
      await adminApi.deactivatePromo(id);
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <AdminShell>
      <PageHeader eyebrow="ADMIN · PROMOS" title="Coupon codes" />
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

      <Section title="Create promo">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Input
            label="CODE"
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="LAUNCH50"
            hint="Alphanumeric, plus _ and -"
          />
          <Input
            label="CREDIT (₹)"
            type="number"
            min={1}
            value={creditRupees}
            onChange={(e) => setCreditRupees(e.target.value)}
          />
          <Input
            label="MAX REDEMPTIONS"
            type="number"
            min={0}
            value={maxRedemptions}
            hint="0 = unlimited"
            onChange={(e) => setMaxRedemptions(e.target.value)}
          />
          <Input
            label="EXPIRES IN DAYS"
            type="number"
            min={1}
            value={expiresInDays}
            hint="Empty = no expiry"
            onChange={(e) => setExpiresInDays(e.target.value)}
          />
        </div>
        <Btn variant="primary" disabled={busy} onClick={create}>
          {busy ? 'Creating…' : 'Create'}
        </Btn>
      </Section>

      <Section title={`Promo codes · ${items.length}`}>
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
                <th style={{ padding: '8px 12px' }}>CODE</th>
                <th style={{ padding: '8px 12px' }}>CREDIT</th>
                <th style={{ padding: '8px 12px' }}>REDEEMED</th>
                <th style={{ padding: '8px 12px' }}>EXPIRES</th>
                <th style={{ padding: '8px 12px' }}>STATUS</th>
                <th style={{ padding: '8px 12px' }}></th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} style={{ borderTop: '1px solid var(--c-line)' }}>
                  <td
                    style={{
                      padding: '10px 12px',
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 600,
                    }}
                  >
                    {p.code}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)' }}>
                    {rupees(p.credit_paise)}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)' }}>
                    {p.times_redeemed}
                    {p.max_redemptions > 0 ? ` / ${p.max_redemptions}` : ''}
                  </td>
                  <td
                    style={{
                      padding: '10px 12px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 12,
                      color: 'var(--c-ink-3)',
                    }}
                  >
                    {p.expires_at ? p.expires_at.slice(0, 10) : '—'}
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    {p.active ? (
                      <Tag tone="mint">active</Tag>
                    ) : (
                      <Tag tone="neutral">off</Tag>
                    )}
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    {p.active && (
                      <Btn
                        size="sm"
                        variant="outline"
                        onClick={() => deactivate(p.id)}
                      >
                        Deactivate
                      </Btn>
                    )}
                  </td>
                </tr>
              ))}
              {!items.length && (
                <tr>
                  <td
                    colSpan={6}
                    style={{
                      padding: '24px 12px',
                      textAlign: 'center',
                      color: 'var(--c-ink-3)',
                    }}
                  >
                    No promos yet.
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
