import * as React from 'react';

type BtnVariant = 'primary' | 'accent' | 'secondary' | 'ghost' | 'soft' | 'outline';
type BtnSize = 'sm' | 'md' | 'lg' | 'xl';

const sizes: Record<BtnSize, { p: string; h: number; fs: number; gap: number }> = {
  sm: { p: '6px 10px', h: 28, fs: 12, gap: 6 },
  md: { p: '9px 14px', h: 36, fs: 13.5, gap: 7 },
  lg: { p: '12px 20px', h: 44, fs: 15, gap: 8 },
  xl: { p: '14px 24px', h: 52, fs: 16, gap: 10 },
};

const variants: Record<BtnVariant, { bg: string; color: string; border: string }> = {
  primary: { bg: 'var(--c-ink)', color: '#faf8f3', border: '1px solid var(--c-ink)' },
  accent: { bg: 'var(--c-accent)', color: '#fff', border: '1px solid var(--c-accent)' },
  secondary: { bg: 'var(--c-surface)', color: 'var(--c-ink)', border: '1px solid var(--c-line-2)' },
  ghost: { bg: 'transparent', color: 'var(--c-ink-2)', border: '1px solid transparent' },
  soft: { bg: 'var(--c-accent-2)', color: 'var(--c-accent-ink)', border: '1px solid transparent' },
  outline: { bg: 'transparent', color: 'var(--c-ink)', border: '1px solid var(--c-ink)' },
};

export type BtnProps = {
  variant?: BtnVariant;
  size?: BtnSize;
  icon?: React.ReactNode;
  iconRight?: React.ReactNode;
  full?: boolean;
  style?: React.CSSProperties;
} & React.ButtonHTMLAttributes<HTMLButtonElement>;

export const Btn = ({
  variant = 'primary',
  size = 'md',
  icon,
  iconRight,
  children,
  disabled,
  full,
  style,
  ...rest
}: BtnProps) => {
  const sz = sizes[size];
  const v = variants[variant];
  return (
    <button
      disabled={disabled}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: sz.gap,
        padding: sz.p,
        height: sz.h,
        fontSize: sz.fs,
        fontWeight: 500,
        borderRadius: variant === 'accent' || variant === 'primary' ? 999 : 'var(--r-md)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        width: full ? '100%' : 'auto',
        letterSpacing: '-0.005em',
        transition: 'transform .08s, box-shadow .12s',
        opacity: disabled ? 0.5 : 1,
        background: v.bg,
        color: v.color,
        border: v.border,
        ...style,
      }}
      {...rest}
    >
      {icon}
      {children}
      {iconRight}
    </button>
  );
};

type Tone = 'neutral' | 'accent' | 'mint' | 'gold' | 'violet' | 'rose' | 'error' | 'ink';

const tones: Record<Tone, { bg: string; color: string }> = {
  neutral: { bg: 'var(--c-surface-2)', color: 'var(--c-ink-2)' },
  accent: { bg: 'var(--c-accent-2)', color: 'var(--c-accent-ink)' },
  mint: { bg: 'var(--c-mint-bg)', color: 'var(--c-mint)' },
  gold: { bg: 'var(--c-gold-bg)', color: 'var(--c-gold)' },
  violet: { bg: 'var(--c-violet-bg)', color: 'var(--c-violet)' },
  rose: { bg: 'var(--c-rose-bg)', color: 'var(--c-rose)' },
  error: { bg: 'var(--c-error-bg)', color: 'var(--c-error)' },
  ink: { bg: 'var(--c-ink)', color: 'var(--c-bg)' },
};

export const Tag = ({
  tone = 'neutral',
  children,
  style,
}: {
  tone?: Tone;
  children: React.ReactNode;
  style?: React.CSSProperties;
}) => {
  const t = tones[tone];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '3px 8px',
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 500,
        letterSpacing: '0.01em',
        background: t.bg,
        color: t.color,
        ...style,
      }}
    >
      {children}
    </span>
  );
};

export const Card = ({
  children,
  style,
  pad = 20,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
  pad?: number;
}) => (
  <div
    style={{
      background: 'var(--c-surface)',
      borderRadius: 'var(--r-lg)',
      border: '1px solid var(--c-line)',
      padding: pad,
      ...style,
    }}
  >
    {children}
  </div>
);

export const CSLogo = ({ size = 18, color }: { size?: number; color?: string }) => (
  <span
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 8,
      fontFamily: 'var(--font-serif)',
      color: color || 'var(--c-ink)',
      fontSize: size + 6,
      lineHeight: 1,
      letterSpacing: '-0.01em',
      fontWeight: 400,
    }}
  >
    <span style={{ display: 'inline-flex', position: 'relative', width: size, height: size }}>
      <span
        style={{
          position: 'absolute',
          inset: 0,
          background: 'var(--c-accent)',
          borderRadius: size * 0.22,
          transform: 'rotate(-6deg)',
        }}
      />
      <span
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontFamily: 'var(--font-serif)',
          fontSize: size * 0.7,
          fontStyle: 'italic',
          fontWeight: 500,
          transform: 'translateY(-1px)',
        }}
      >
        c
      </span>
    </span>
    <span style={{ fontStyle: 'italic' }}>Cheatsheet</span>
  </span>
);
