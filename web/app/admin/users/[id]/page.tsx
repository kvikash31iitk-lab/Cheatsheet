'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import {
  AdminShell,
  Input,
  PageHeader,
  Section,
  Textarea,
  Toggle,
} from '@/components/admin-shell';
import { Btn, Tag } from '@/components/ui';
import { adminApi, type AdminUserDetail } from '@/lib/admin-api';

function rupees(paise: number): string {
  const sign = paise < 0 ? '−' : '';
  return `${sign}₹${(Math.abs(paise) / 100).toLocaleString('en-IN', {
    maximumFractionDigits: 2,
  })}`;
}

export default function AdminUserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<AdminUserDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Credit form
  const [creditAmount, setCreditAmount] = useState('');
  const [creditReason, setCreditReason] = useState('');
  const [creditBusy, setCreditBusy] = useState(false);

  // Override form local state
  const [bypassPaid, setBypassPaid] = useState(false);
  const [isBanned, setIsBanned] = useState(false);
  const [overrideCheats, setOverrideCheats] = useState('');
  const [overrideBooks, setOverrideBooks] = useState('');
  const [promptCheats, setPromptCheats] = useState('');
  const [promptBook, setPromptBook] = useState('');
  const [updateBusy, setUpdateBusy] = useState(false);

  async function load() {
    setError(null);
    try {
      const d = await adminApi.getUser(id);
      setData(d);
      setBypassPaid(d.user.bypass_paid);
      setIsBanned(d.user.is_banned);
      setOverrideCheats(
        d.user.daily_cheatsheets_override === null
          ? ''
          : String(d.user.daily_cheatsheets_override),
      );
      setOverrideBooks(
        d.user.daily_books_override === null
          ? ''
          : String(d.user.daily_books_override),
      );
      setPromptCheats(d.user.custom_prompt_cheatsheet ?? '');
      setPromptBook(d.user.custom_prompt_book ?? '');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => {
    if (id) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function applyCredit(direction: 1 | -1) {
    if (!creditAmount || !creditReason) return;
    const value = Math.round(Number(creditAmount) * 100) * direction;
    if (!Number.isFinite(value) || value === 0) return;
    setCreditBusy(true);
    try {
      await adminApi.creditUser(id, value, creditReason);
      setCreditAmount('');
      setCreditReason('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreditBusy(false);
    }
  }

  async function saveOverrides() {
    setUpdateBusy(true);
    setError(null);
    const patch: Record<string, unknown> = {
      bypass_paid: bypassPaid,
      is_banned: isBanned,
    };
    if (overrideCheats === '') {
      patch.clear_cheatsheets_override = true;
    } else {
      patch.daily_cheatsheets_override = Number(overrideCheats);
    }
    if (overrideBooks === '') {
      patch.clear_books_override = true;
    } else {
      patch.daily_books_override = Number(overrideBooks);
    }
    if (promptCheats.trim() === '') {
      patch.clear_custom_prompt_cheatsheet = true;
    } else {
      patch.custom_prompt_cheatsheet = promptCheats;
    }
    if (promptBook.trim() === '') {
      patch.clear_custom_prompt_book = true;
    } else {
      patch.custom_prompt_book = promptBook;
    }
    try {
      await adminApi.updateUser(id, patch);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUpdateBusy(false);
    }
  }

  if (!data) {
    return (
      <AdminShell>
        <PageHeader eyebrow="ADMIN · USER" title="Loading…" />
        {error && <div style={{ color: 'var(--c-error)' }}>{error}</div>}
      </AdminShell>
    );
  }

  const u = data.user;

  return (
    <AdminShell>
      <PageHeader
        eyebrow={`ADMIN · ${u.id}`}
        title={u.email}
        right={
          <div style={{ display: 'flex', gap: 6 }}>
            {u.is_admin && <Tag tone="violet">admin</Tag>}
            {u.bypass_paid && <Tag tone="mint">free path</Tag>}
            {u.is_banned && <Tag tone="error">banned</Tag>}
          </div>
        }
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

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Section title="Profile">
          <Row label="Name">{u.name ?? '—'}</Row>
          <Row label="Joined">{u.created_at?.slice(0, 10) ?? '—'}</Row>
          <Row label="Last seen">{u.last_seen_at?.slice(0, 16).replace('T', ' ') ?? '—'}</Row>
          <Row label="Wallet">{rupees(u.wallet_balance_paise)}</Row>
          <Row label="Referral code">{u.referral_code ?? '—'}</Row>
          <Row label="Referred by">{u.referred_by_code ?? '—'}</Row>
          <Row label="Today">
            {u.today_cheatsheets} cheats · {u.today_books} books
          </Row>
          <Row label="Lifetime">{u.total_generations} generations</Row>
        </Section>

        <Section title="Credit wallet" description="Reason becomes a transaction note.">
          <Input
            label="AMOUNT (₹)"
            type="number"
            min={1}
            value={creditAmount}
            onChange={(e) => setCreditAmount(e.target.value)}
            placeholder="100"
          />
          <Input
            label="REASON"
            value={creditReason}
            onChange={(e) => setCreditReason(e.target.value)}
            placeholder="Refund for failed gen"
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn
              variant="primary"
              disabled={creditBusy}
              onClick={() => applyCredit(1)}
            >
              Credit +
            </Btn>
            <Btn
              variant="outline"
              disabled={creditBusy}
              onClick={() => applyCredit(-1)}
            >
              Debit −
            </Btn>
          </div>
        </Section>
      </div>

      <Section title="Overrides" description="Leave empty to use the global default.">
        <Toggle
          label="Bypass paid path"
          hint="Every generation is free for this user, no wallet debit."
          checked={bypassPaid}
          onChange={setBypassPaid}
        />
        <Toggle
          label="Banned"
          hint="403 on all API calls."
          checked={isBanned}
          onChange={setIsBanned}
        />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Input
            label="DAILY CHEATSHEETS OVERRIDE"
            type="number"
            min={0}
            value={overrideCheats}
            placeholder="empty = use default"
            onChange={(e) => setOverrideCheats(e.target.value)}
          />
          <Input
            label="DAILY BOOKS OVERRIDE"
            type="number"
            min={0}
            value={overrideBooks}
            placeholder="empty = use default"
            onChange={(e) => setOverrideBooks(e.target.value)}
          />
        </div>
        <Textarea
          label="CUSTOM CHEATSHEET PROMPT"
          hint="Empty = use shared system prompt."
          value={promptCheats}
          onChange={(e) => setPromptCheats(e.target.value)}
        />
        <Textarea
          label="CUSTOM BOOK PROMPT"
          hint="Empty = use shared system prompt."
          value={promptBook}
          onChange={(e) => setPromptBook(e.target.value)}
        />
        <Btn variant="primary" disabled={updateBusy} onClick={saveOverrides}>
          {updateBusy ? 'Saving…' : 'Save overrides'}
        </Btn>
      </Section>

      <Section title={`Recent transactions · ${data.transactions.length}`}>
        {data.transactions.length === 0 ? (
          <div style={{ color: 'var(--c-ink-3)', fontSize: 13 }}>None.</div>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {data.transactions.map((tx) => (
              <li
                key={tx.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '8px 0',
                  borderBottom: '1px solid var(--c-line)',
                  fontSize: 13,
                }}
              >
                <div>
                  <span style={{ fontWeight: 500 }}>{tx.kind}</span>
                  <span style={{ color: 'var(--c-ink-3)', marginLeft: 8 }}>
                    {tx.note ?? '—'}
                  </span>
                </div>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    color: tx.amount_paise > 0 ? 'var(--c-mint)' : 'var(--c-ink)',
                  }}
                >
                  {rupees(tx.amount_paise)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={`Recent generations · ${data.generations.length}`}>
        {data.generations.length === 0 ? (
          <div style={{ color: 'var(--c-ink-3)', fontSize: 13 }}>None.</div>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {data.generations.map((g) => (
              <li
                key={g.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '8px 0',
                  borderBottom: '1px solid var(--c-line)',
                  fontSize: 13,
                  gap: 12,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {g.title ?? '(no title yet)'}
                  </div>
                  <div style={{ fontSize: 11.5, color: 'var(--c-ink-3)' }}>
                    {g.kind} · {g.status}
                    {g.error_message ? ` · ${g.error_message}` : ''}
                  </div>
                </div>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 12,
                    color: 'var(--c-ink-3)',
                  }}
                >
                  {g.was_free ? 'free' : rupees(g.cost_paise)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={`Admin actions on this user · ${data.audit.length}`}>
        {data.audit.length === 0 ? (
          <div style={{ color: 'var(--c-ink-3)', fontSize: 13 }}>None.</div>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {data.audit.map((a) => (
              <li
                key={a.id}
                style={{
                  padding: '8px 0',
                  borderBottom: '1px solid var(--c-line)',
                  fontSize: 13,
                }}
              >
                <div>
                  <span style={{ fontWeight: 500 }}>{a.action}</span>
                  <span style={{ color: 'var(--c-ink-3)', marginLeft: 8 }}>
                    by {a.admin_email}
                  </span>
                </div>
                {a.payload && (
                  <pre
                    style={{
                      fontSize: 11,
                      color: 'var(--c-ink-3)',
                      margin: '4px 0 0',
                      whiteSpace: 'pre-wrap',
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
