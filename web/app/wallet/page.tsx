'use client';

import { useEffect, useState } from 'react';
import Script from 'next/script';
import { AppBar } from '@/components/app-bar';
import { Btn, Tag } from '@/components/ui';
import { Ic } from '@/components/icons';
import {
  createWalletOrder,
  verifyWalletPayment,
  getMe,
  getTransactions,
  type Me,
  type Transaction,
} from '@/lib/api';

const PRESETS = [100, 200, 500];
const MIN_TOPUP = 100;

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => { open: () => void };
  }
}

export default function WalletPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [txs, setTxs] = useState<Transaction[] | null>(null);
  const [amount, setAmount] = useState<number>(200);
  const [custom, setCustom] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function refresh() {
    try {
      const [m, t] = await Promise.all([getMe(), getTransactions()]);
      setMe(m);
      setTxs(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function topUp() {
    setError(null);
    setSuccess(null);
    const value = custom ? parseInt(custom, 10) : amount;
    if (!Number.isFinite(value) || value < MIN_TOPUP) {
      setError(`Minimum top-up is ₹${MIN_TOPUP}`);
      return;
    }
    if (typeof window === 'undefined' || !window.Razorpay) {
      setError('Razorpay not loaded yet — try again in a moment');
      return;
    }
    setBusy(true);
    try {
      const order = await createWalletOrder(value * 100);
      const rzp = new window.Razorpay({
        key: order.key_id,
        amount: order.amount_paise,
        currency: order.currency,
        order_id: order.order_id,
        name: 'Cheatsheet',
        description: `Wallet top-up · ₹${value}`,
        // UPI-only — no cards/netbanking/wallets.
        method: { upi: true, card: false, netbanking: false, wallet: false },
        prefill: { email: me?.email ?? '', name: me?.name ?? '' },
        theme: { color: '#c9572b' },
        handler: async (response: Record<string, string>) => {
          try {
            await verifyWalletPayment({
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            });
            setSuccess(`₹${value} added to your wallet`);
            await refresh();
          } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
          }
        },
        modal: {
          ondismiss: () => setBusy(false),
        },
      });
      rzp.open();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const balanceRupees = ((me?.wallet_balance_paise ?? 0) / 100).toFixed(2);

  return (
    <main style={{ minHeight: '100vh' }}>
      <Script
        src="https://checkout.razorpay.com/v1/checkout.js"
        strategy="lazyOnload"
      />
      <AppBar />

      <div style={{ padding: 32, maxWidth: 1100, margin: '0 auto' }}>
        <div style={{ marginBottom: 24 }}>
          <div
            style={{
              fontSize: 11.5,
              color: 'var(--c-ink-3)',
              fontFamily: 'var(--font-mono)',
              letterSpacing: '.08em',
              marginBottom: 4,
            }}
          >
            WALLET
          </div>
          <h1
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 36,
              fontWeight: 400,
              letterSpacing: '-0.015em',
              margin: 0,
              color: 'var(--c-ink)',
            }}
          >
            Top up once, spend per generation.
          </h1>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1.4fr',
            gap: 24,
          }}
        >
          {/* Left col */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Balance */}
            <div
              style={{
                background: 'var(--c-ink)',
                color: 'var(--c-bg)',
                borderRadius: 16,
                padding: 28,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  marginBottom: 14,
                }}
              >
                <span
                  style={{
                    fontSize: 11.5,
                    color: '#b8b0a6',
                    fontFamily: 'var(--font-mono)',
                    letterSpacing: '.08em',
                  }}
                >
                  BALANCE
                </span>
                <span style={{ fontSize: 11, color: '#7fb37b' }}>● Active</span>
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-serif)',
                  fontSize: 56,
                  lineHeight: 1,
                  fontStyle: 'italic',
                  letterSpacing: '-0.02em',
                  marginBottom: 6,
                }}
              >
                ₹{balanceRupees.split('.')[0]}
                <span style={{ fontSize: 26 }}>.{balanceRupees.split('.')[1]}</span>
              </div>
              <div style={{ fontSize: 13, color: '#b8b0a6' }}>
                ≈ {Math.floor((me?.wallet_balance_paise ?? 0) / 100)} 30-min cheatsheets
              </div>
            </div>

            {/* Top-up */}
            <div
              style={{
                background: 'var(--c-surface)',
                border: '1px solid var(--c-line)',
                borderRadius: 14,
                padding: 20,
              }}
            >
              <div
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  color: 'var(--c-ink)',
                  marginBottom: 4,
                }}
              >
                Quick top-up
              </div>
              <div
                style={{
                  fontSize: 12,
                  color: 'var(--c-ink-3)',
                  marginBottom: 14,
                }}
              >
                UPI only · powered by Razorpay · minimum ₹{MIN_TOPUP}
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(3, 1fr)',
                  gap: 8,
                  marginBottom: 12,
                }}
              >
                {PRESETS.map((v) => {
                  const selected = !custom && amount === v;
                  return (
                    <button
                      key={v}
                      onClick={() => {
                        setAmount(v);
                        setCustom('');
                      }}
                      style={{
                        padding: 14,
                        borderRadius: 10,
                        border: `${selected ? '1.5px' : '1px'} solid ${
                          selected ? 'var(--c-accent)' : 'var(--c-line-2)'
                        }`,
                        background: selected ? 'var(--c-accent-2)' : 'var(--c-surface)',
                        cursor: 'pointer',
                        textAlign: 'center',
                        fontFamily: 'inherit',
                      }}
                    >
                      <div
                        style={{
                          fontFamily: 'var(--font-serif)',
                          fontSize: 22,
                          color: selected ? 'var(--c-accent-ink)' : 'var(--c-ink)',
                          fontStyle: 'italic',
                        }}
                      >
                        ₹{v}
                      </div>
                      <div
                        style={{
                          fontSize: 10.5,
                          color: selected ? 'var(--c-accent-ink)' : 'var(--c-ink-3)',
                          marginTop: 2,
                        }}
                      >
                        ~{v} cheats
                      </div>
                    </button>
                  );
                })}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  placeholder={`Custom amount (min ₹${MIN_TOPUP})`}
                  inputMode="numeric"
                  value={custom}
                  onChange={(e) => setCustom(e.target.value.replace(/[^0-9]/g, ''))}
                  style={{
                    flex: 1,
                    padding: '11px 14px',
                    borderRadius: 10,
                    border: '1px solid var(--c-line-2)',
                    background: 'var(--c-surface-2)',
                    fontSize: 13.5,
                    outline: 'none',
                  }}
                />
                <Btn variant="primary" size="md" disabled={busy} onClick={topUp}>
                  {busy ? 'Opening…' : `Pay ₹${custom || amount}`}
                </Btn>
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: 'var(--c-ink-3)',
                  marginTop: 10,
                  fontFamily: 'var(--font-mono)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <Ic.shield size={11} sw={1.6} /> SECURE · UPI · INSTANT
              </div>
              {error && (
                <div
                  style={{
                    background: 'var(--c-error-bg)',
                    color: 'var(--c-error)',
                    padding: 10,
                    borderRadius: 8,
                    fontSize: 12,
                    marginTop: 10,
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
                    padding: 10,
                    borderRadius: 8,
                    fontSize: 12,
                    marginTop: 10,
                  }}
                >
                  {success}
                </div>
              )}
            </div>
          </div>

          {/* Right col: ledger */}
          <div
            style={{
              background: 'var(--c-surface)',
              border: '1px solid var(--c-line)',
              borderRadius: 14,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '16px 20px',
                borderBottom: '1px solid var(--c-line)',
                fontSize: 14,
                fontWeight: 600,
                color: 'var(--c-ink)',
              }}
            >
              Transactions
            </div>
            {txs === null ? (
              <div style={{ padding: 24, fontSize: 13, color: 'var(--c-ink-3)' }}>
                Loading…
              </div>
            ) : txs.length === 0 ? (
              <div
                style={{
                  padding: 32,
                  textAlign: 'center',
                  fontSize: 13,
                  color: 'var(--c-ink-3)',
                }}
              >
                No transactions yet — top up to begin.
              </div>
            ) : (
              txs.map((tx, i) => (
                <TxRow key={tx.id} tx={tx} last={i === txs.length - 1} />
              ))
            )}
          </div>
        </div>
      </div>
    </main>
  );
}

function TxRow({ tx, last }: { tx: Transaction; last: boolean }) {
  const isCredit = tx.amount_paise > 0;
  const isPending = tx.status === 'pending';
  const isFailed = tx.status === 'failed';
  const sign = isCredit ? '+' : '−';
  const rupees = (Math.abs(tx.amount_paise) / 100).toFixed(2);
  const tone =
    tx.kind === 'topup'
      ? 'mint'
      : tx.kind === 'refund'
        ? 'mint'
        : 'neutral';

  const label =
    tx.kind === 'topup'
      ? 'Top-up'
      : tx.kind === 'refund'
        ? 'Refund · auto on failure'
        : tx.note?.startsWith('cheatsheet')
          ? `Cheatsheet${tx.note ? ' · ' + tx.note.split('· ')[1] : ''}`
          : tx.note?.startsWith('book')
            ? `Book Notes${tx.note ? ' · ' + tx.note.split('· ')[1] : ''}`
            : 'Generation';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '14px 20px',
        borderBottom: last ? 'none' : '1px solid var(--c-line)',
      }}
    >
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: 8,
          background: tone === 'mint' ? 'var(--c-mint-bg)' : 'var(--c-surface-2)',
          color: tone === 'mint' ? 'var(--c-mint)' : 'var(--c-ink-3)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {tx.kind === 'refund' ? (
          <Ic.refresh size={14} />
        ) : isCredit ? (
          <Ic.plus size={14} />
        ) : (
          <Ic.zap size={14} />
        )}
      </div>
      <div style={{ flex: 1 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 500,
            color: 'var(--c-ink)',
            display: 'flex',
            gap: 6,
            alignItems: 'center',
          }}
        >
          {label}
          {isPending && <Tag tone="gold">Pending</Tag>}
          {isFailed && <Tag tone="error">Failed</Tag>}
        </div>
        <div
          style={{
            fontSize: 11.5,
            color: 'var(--c-ink-3)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {tx.created_at
            ? new Date(tx.created_at).toLocaleString('en-IN', {
                day: '2-digit',
                month: 'short',
                hour: '2-digit',
                minute: '2-digit',
              })
            : ''}
        </div>
      </div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 13,
          fontWeight: 500,
          color: isCredit ? 'var(--c-mint)' : 'var(--c-ink)',
        }}
      >
        {sign}₹{rupees}
      </div>
    </div>
  );
}
