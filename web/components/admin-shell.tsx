'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import * as React from 'react';
import { AppBar } from '@/components/app-bar';
import { Ic } from '@/components/icons';

type NavItem = {
  href: string;
  label: string;
  icon: React.ReactNode;
  exact?: boolean;
};

const NAV: NavItem[] = [
  { href: '/admin', label: 'Overview', icon: <Ic.trend size={14} />, exact: true },
  { href: '/admin/settings', label: 'Settings', icon: <Ic.cog size={14} /> },
  { href: '/admin/users', label: 'Users', icon: <Ic.user size={14} /> },
  { href: '/admin/generations', label: 'Generations', icon: <Ic.list size={14} /> },
  { href: '/admin/upsc', label: 'UPSC digest', icon: <Ic.list size={14} /> },
  { href: '/admin/broadcasts', label: 'Broadcasts', icon: <Ic.bell size={14} /> },
  { href: '/admin/promos', label: 'Promo codes', icon: <Ic.coin size={14} /> },
  { href: '/admin/blocks', label: 'Block rules', icon: <Ic.shield size={14} /> },
  { href: '/admin/payments', label: 'Failed payments', icon: <Ic.wallet size={14} /> },
  { href: '/admin/cookies', label: 'yt-dlp cookies', icon: <Ic.refresh size={14} /> },
  { href: '/admin/audit', label: 'Audit log', icon: <Ic.hist size={14} /> },
];

export function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <main style={{ minHeight: '100vh' }}>
      <AppBar />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '220px 1fr',
          minHeight: 'calc(100vh - 73px)',
        }}
      >
        <aside
          style={{
            borderRight: '1px solid var(--c-line)',
            padding: '24px 16px',
            background: 'var(--c-surface-2, #f5f1ea)',
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: 'var(--c-ink-3)',
              fontFamily: 'var(--font-mono)',
              letterSpacing: '.08em',
              marginBottom: 10,
              paddingLeft: 10,
            }}
          >
            ADMIN
          </div>
          <nav style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {NAV.map((item) => {
              const active = item.exact
                ? pathname === item.href
                : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 9,
                    padding: '8px 10px',
                    borderRadius: 8,
                    fontSize: 13,
                    color: active ? 'var(--c-ink)' : 'var(--c-ink-2)',
                    background: active ? 'var(--c-surface)' : 'transparent',
                    textDecoration: 'none',
                    fontWeight: active ? 500 : 400,
                  }}
                >
                  {item.icon}
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </aside>
        <section style={{ padding: '28px 36px', maxWidth: 1100 }}>{children}</section>
      </div>
    </main>
  );
}

export function PageHeader({
  eyebrow,
  title,
  right,
}: {
  eyebrow: string;
  title: string;
  right?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
        marginBottom: 24,
        gap: 16,
      }}
    >
      <div>
        <div
          style={{
            fontSize: 11.5,
            color: 'var(--c-ink-3)',
            fontFamily: 'var(--font-mono)',
            letterSpacing: '.08em',
            marginBottom: 4,
          }}
        >
          {eyebrow}
        </div>
        <h1
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 32,
            fontWeight: 400,
            letterSpacing: '-0.015em',
            margin: 0,
            color: 'var(--c-ink)',
          }}
        >
          {title}
        </h1>
      </div>
      {right}
    </div>
  );
}

export function Section({
  title,
  description,
  children,
  right,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <section
      style={{
        background: 'var(--c-surface)',
        border: '1px solid var(--c-line)',
        borderRadius: 14,
        marginBottom: 16,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: '14px 18px',
          borderBottom: '1px solid var(--c-line)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
        }}
      >
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--c-ink)' }}>
            {title}
          </div>
          {description && (
            <div style={{ fontSize: 12, color: 'var(--c-ink-3)', marginTop: 2 }}>
              {description}
            </div>
          )}
        </div>
        {right}
      </div>
      <div style={{ padding: 18 }}>{children}</div>
    </section>
  );
}

export function Input({
  label,
  hint,
  type = 'text',
  ...rest
}: { label: string; hint?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label style={{ display: 'block', marginBottom: 12 }}>
      <div
        style={{
          fontSize: 11,
          color: 'var(--c-ink-3)',
          fontFamily: 'var(--font-mono)',
          letterSpacing: '.06em',
          marginBottom: 5,
        }}
      >
        {label}
      </div>
      <input
        type={type}
        {...rest}
        style={{
          width: '100%',
          padding: '9px 12px',
          borderRadius: 8,
          border: '1px solid var(--c-line-2)',
          background: 'var(--c-surface-2)',
          fontSize: 13.5,
          outline: 'none',
          fontFamily: 'inherit',
          ...rest.style,
        }}
      />
      {hint && (
        <div style={{ fontSize: 11, color: 'var(--c-ink-3)', marginTop: 4 }}>
          {hint}
        </div>
      )}
    </label>
  );
}

export function Textarea({
  label,
  hint,
  ...rest
}: { label: string; hint?: string } & React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <label style={{ display: 'block', marginBottom: 12 }}>
      <div
        style={{
          fontSize: 11,
          color: 'var(--c-ink-3)',
          fontFamily: 'var(--font-mono)',
          letterSpacing: '.06em',
          marginBottom: 5,
        }}
      >
        {label}
      </div>
      <textarea
        {...rest}
        style={{
          width: '100%',
          minHeight: 80,
          padding: '9px 12px',
          borderRadius: 8,
          border: '1px solid var(--c-line-2)',
          background: 'var(--c-surface-2)',
          fontSize: 13.5,
          outline: 'none',
          fontFamily: 'inherit',
          resize: 'vertical',
          ...rest.style,
        }}
      />
      {hint && (
        <div style={{ fontSize: 11, color: 'var(--c-ink-3)', marginTop: 4 }}>
          {hint}
        </div>
      )}
    </label>
  );
}

export function Select({
  label,
  hint,
  children,
  ...rest
}: { label: string; hint?: string } & React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <label style={{ display: 'block', marginBottom: 12 }}>
      <div
        style={{
          fontSize: 11,
          color: 'var(--c-ink-3)',
          fontFamily: 'var(--font-mono)',
          letterSpacing: '.06em',
          marginBottom: 5,
        }}
      >
        {label}
      </div>
      <select
        {...rest}
        style={{
          width: '100%',
          padding: '9px 12px',
          borderRadius: 8,
          border: '1px solid var(--c-line-2)',
          background: 'var(--c-surface-2)',
          fontSize: 13.5,
          outline: 'none',
          fontFamily: 'inherit',
          ...rest.style,
        }}
      >
        {children}
      </select>
      {hint && (
        <div style={{ fontSize: 11, color: 'var(--c-ink-3)', marginTop: 4 }}>
          {hint}
        </div>
      )}
    </label>
  );
}

export function Toggle({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 16,
        marginBottom: 12,
        cursor: 'pointer',
      }}
    >
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--c-ink)' }}>
          {label}
        </div>
        {hint && (
          <div style={{ fontSize: 11.5, color: 'var(--c-ink-3)', marginTop: 2 }}>
            {hint}
          </div>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        style={{
          width: 38,
          height: 22,
          borderRadius: 11,
          background: checked ? 'var(--c-accent)' : 'var(--c-line-2)',
          position: 'relative',
          border: 'none',
          cursor: 'pointer',
          flex: 'none',
          marginTop: 2,
        }}
      >
        <span
          style={{
            position: 'absolute',
            top: 2,
            left: checked ? 18 : 2,
            width: 18,
            height: 18,
            borderRadius: '50%',
            background: '#fff',
            transition: 'left .15s',
          }}
        />
      </button>
    </label>
  );
}
