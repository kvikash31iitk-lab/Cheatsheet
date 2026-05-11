'use client';

import { useEffect, useState } from 'react';
import {
  AdminShell,
  Input,
  PageHeader,
  Section,
  Select,
  Textarea,
  Toggle,
} from '@/components/admin-shell';
import { Btn } from '@/components/ui';
import { adminApi, type AdminSettings } from '@/lib/admin-api';

export default function AdminSettingsPage() {
  const [s, setS] = useState<AdminSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    adminApi.getSettings().then(setS).catch((e) => setError(String(e)));
  }, []);

  function update<K extends keyof AdminSettings>(key: K, value: AdminSettings[K]) {
    setS((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  async function save() {
    if (!s) return;
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const next = await adminApi.updateSettings(s);
      setS(next);
      setSuccess('Saved.');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!s) {
    return (
      <AdminShell>
        <PageHeader eyebrow="ADMIN" title="Settings" />
        <div style={{ color: 'var(--c-ink-3)' }}>{error ?? 'Loading…'}</div>
      </AdminShell>
    );
  }

  return (
    <AdminShell>
      <PageHeader
        eyebrow="ADMIN · SETTINGS"
        title="Tune the knobs"
        right={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {success && (
              <span style={{ color: 'var(--c-mint)', fontSize: 12 }}>{success}</span>
            )}
            <Btn variant="primary" disabled={busy} onClick={save}>
              {busy ? 'Saving…' : 'Save all'}
            </Btn>
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

      <Section
        title="Maintenance"
        description="Disables generation for everyone except admins."
      >
        <Toggle
          label="Maintenance mode"
          hint="When on, /api/generate returns 503 and the web app shows a banner."
          checked={s.maintenance_mode}
          onChange={(v) => update('maintenance_mode', v)}
        />
        <Textarea
          label="MAINTENANCE MESSAGE"
          hint="Shown to non-admin users when they try to generate."
          value={s.maintenance_message}
          onChange={(e) => update('maintenance_message', e.target.value)}
        />
      </Section>

      <Section
        title="Free tier"
        description="Defaults applied to every user. Per-user overrides live on the user page."
      >
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Input
            label="FREE CHEATSHEETS / DAY"
            type="number"
            min={0}
            value={s.free_cheatsheets_per_day}
            onChange={(e) =>
              update('free_cheatsheets_per_day', Number(e.target.value))
            }
          />
          <Input
            label="FREE BOOKS / DAY"
            type="number"
            min={0}
            value={s.free_books_per_day}
            onChange={(e) =>
              update('free_books_per_day', Number(e.target.value))
            }
          />
        </div>
      </Section>

      <Section
        title="Pricing"
        description="Paise per 30-minute slab, rounded up. 1 paisa = ₹0.01."
      >
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Input
            label="CHEATSHEET (PAISE / 30MIN)"
            type="number"
            min={0}
            value={s.cost_paise_per_30min_cheatsheet}
            hint={`= ₹${(s.cost_paise_per_30min_cheatsheet / 100).toFixed(2)} per 30-min slab`}
            onChange={(e) =>
              update('cost_paise_per_30min_cheatsheet', Number(e.target.value))
            }
          />
          <Input
            label="BOOK (PAISE / 30MIN)"
            type="number"
            min={0}
            value={s.cost_paise_per_30min_book}
            hint={`= ₹${(s.cost_paise_per_30min_book / 100).toFixed(2)} per 30-min slab`}
            onChange={(e) =>
              update('cost_paise_per_30min_book', Number(e.target.value))
            }
          />
        </div>
        <Input
          label="MIN TOP-UP (PAISE)"
          type="number"
          min={100}
          value={s.min_topup_paise}
          hint={`= ₹${(s.min_topup_paise / 100).toFixed(0)}. Razorpay min is ₹1.`}
          onChange={(e) => update('min_topup_paise', Number(e.target.value))}
        />
      </Section>

      <Section
        title="Rate limits"
        description="Per-user caps to keep abusive use from blowing up cost."
      >
        <Input
          label="MAX GENERATIONS / HOUR / USER"
          type="number"
          min={0}
          value={s.max_generations_per_hour_per_user}
          hint="0 = unlimited"
          onChange={(e) =>
            update('max_generations_per_hour_per_user', Number(e.target.value))
          }
        />
      </Section>

      <Section
        title="Growth"
        description="Referral system: each side gets this credit when a new user joins via a referral code."
      >
        <Input
          label="REFERRAL CREDIT (PAISE)"
          type="number"
          min={0}
          value={s.referral_credit_paise}
          hint={`= ₹${(s.referral_credit_paise / 100).toFixed(2)} per side`}
          onChange={(e) => update('referral_credit_paise', Number(e.target.value))}
        />
      </Section>

      <Section
        title="Tech toggles"
        description="Swap providers without redeploying. Effect applies to new generations."
      >
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Select
            label="AUTHORING PROVIDER"
            value={s.authoring_provider}
            onChange={(e) =>
              update(
                'authoring_provider',
                e.target.value as AdminSettings['authoring_provider'],
              )
            }
          >
            <option value="claude_code">claude_code (Max sub)</option>
            <option value="groq">groq (free, lossy)</option>
            <option value="openai">openai (paid)</option>
            <option value="anthropic">anthropic (paid)</option>
          </Select>
          <Select
            label="WHISPER BACKEND"
            value={s.whisper_backend}
            onChange={(e) =>
              update(
                'whisper_backend',
                e.target.value as AdminSettings['whisper_backend'],
              )
            }
          >
            <option value="local">local (faster-whisper)</option>
            <option value="groq">groq (rate-limited)</option>
            <option value="openai">openai (paid)</option>
          </Select>
        </div>
      </Section>
    </AdminShell>
  );
}
