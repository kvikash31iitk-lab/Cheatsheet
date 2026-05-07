import * as React from 'react';

type IconProps = {
  size?: number;
  sw?: number;
  fill?: string;
  children?: React.ReactNode;
  d?: string;
};

const Icon = ({ d, size = 16, sw = 1.6, fill = 'none', children }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill={fill}
    stroke="currentColor"
    strokeWidth={sw}
    strokeLinecap="round"
    strokeLinejoin="round"
    style={{ flex: 'none' }}
  >
    {d ? <path d={d} /> : children}
  </svg>
);

type P = { size?: number; sw?: number };

export const Ic = {
  play: (p: P = {}) => (
    <Icon {...p}>
      <polygon points="6 4 20 12 6 20 6 4" fill="currentColor" stroke="none" />
    </Icon>
  ),
  sparkle: (p: P = {}) => (
    <Icon {...p}>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8" />
    </Icon>
  ),
  arrow: (p: P = {}) => (
    <Icon {...p}>
      <line x1="5" y1="12" x2="19" y2="12" />
      <polyline points="13 6 19 12 13 18" />
    </Icon>
  ),
  check: (p: P = {}) => (
    <Icon {...p}>
      <polyline points="4 12 10 18 20 6" />
    </Icon>
  ),
  plus: (p: P = {}) => (
    <Icon {...p}>
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </Icon>
  ),
  zap: (p: P = {}) => (
    <Icon {...p}>
      <polygon points="13 2 3 14 11 14 9 22 21 10 13 10 13 2" fill="currentColor" stroke="none" />
    </Icon>
  ),
  book: (p: P = {}) => (
    <Icon {...p}>
      <path d="M4 4h12a3 3 0 0 1 3 3v13H7a3 3 0 0 1-3-3z" />
      <path d="M4 17a3 3 0 0 1 3-3h12" />
    </Icon>
  ),
  list: (p: P = {}) => (
    <Icon {...p}>
      <line x1="4" y1="6" x2="20" y2="6" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="18" x2="14" y2="18" />
    </Icon>
  ),
  wallet: (p: P = {}) => (
    <Icon {...p}>
      <rect x="3" y="6" width="18" height="14" rx="2" />
      <path d="M3 10h18M16 15h2" />
    </Icon>
  ),
  clock: (p: P = {}) => (
    <Icon {...p}>
      <circle cx="12" cy="12" r="9" />
      <polyline points="12 7 12 12 15 14" />
    </Icon>
  ),
  download: (p: P = {}) => (
    <Icon {...p}>
      <path d="M12 4v12M6 12l6 6 6-6M4 20h16" />
    </Icon>
  ),
  search: (p: P = {}) => (
    <Icon {...p}>
      <circle cx="11" cy="11" r="7" />
      <line x1="20" y1="20" x2="16.5" y2="16.5" />
    </Icon>
  ),
  user: (p: P = {}) => (
    <Icon {...p}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 4-7 8-7s8 3 8 7" />
    </Icon>
  ),
  bell: (p: P = {}) => (
    <Icon {...p}>
      <path d="M6 9a6 6 0 0 1 12 0c0 5 2 7 2 7H4s2-2 2-7" />
      <path d="M10 20a2 2 0 0 0 4 0" />
    </Icon>
  ),
  yt: (p: P = {}) => (
    <Icon {...p}>
      <rect x="2" y="5" width="20" height="14" rx="3" fill="#c9572b" stroke="none" />
      <polygon points="10 9 16 12 10 15" fill="#fff" stroke="none" />
    </Icon>
  ),
  link: (p: P = {}) => (
    <Icon {...p}>
      <path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 1 0-5.66-5.66L11.5 7" />
      <path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 1 0 5.66 5.66L12.5 17" />
    </Icon>
  ),
  chev: (p: P = {}) => (
    <Icon {...p}>
      <polyline points="9 6 15 12 9 18" />
    </Icon>
  ),
  chevd: (p: P = {}) => (
    <Icon {...p}>
      <polyline points="6 9 12 15 18 9" />
    </Icon>
  ),
  shield: (p: P = {}) => (
    <Icon {...p}>
      <path d="M12 3l8 3v6c0 4-3 8-8 9-5-1-8-5-8-9V6z" />
    </Icon>
  ),
  star: (p: P = {}) => (
    <Icon {...p}>
      <polygon points="12 3 15 9 21 10 16.5 14.5 18 21 12 17.5 6 21 7.5 14.5 3 10 9 9 12 3" />
    </Icon>
  ),
  copy: (p: P = {}) => (
    <Icon {...p}>
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
    </Icon>
  ),
  hist: (p: P = {}) => (
    <Icon {...p}>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <polyline points="3 3 3 8 8 8" />
      <polyline points="12 7 12 12 16 14" />
    </Icon>
  ),
  cog: (p: P = {}) => (
    <Icon {...p}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19 12a7 7 0 0 0-.1-1.3l2-1.6-2-3.4-2.4.9a7 7 0 0 0-2.2-1.3L14 3h-4l-.3 2.3a7 7 0 0 0-2.2 1.3l-2.4-.9-2 3.4 2 1.6A7 7 0 0 0 5 12c0 .4 0 .9.1 1.3l-2 1.6 2 3.4 2.4-.9c.7.5 1.4 1 2.2 1.3L10 21h4l.3-2.3a7 7 0 0 0 2.2-1.3l2.4.9 2-3.4-2-1.6c.1-.4.1-.9.1-1.3z" />
    </Icon>
  ),
  x: (p: P = {}) => (
    <Icon {...p}>
      <line x1="6" y1="6" x2="18" y2="18" />
      <line x1="6" y1="18" x2="18" y2="6" />
    </Icon>
  ),
  menu: (p: P = {}) => (
    <Icon {...p}>
      <line x1="4" y1="7" x2="20" y2="7" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="17" x2="20" y2="17" />
    </Icon>
  ),
  coin: (p: P = {}) => (
    <Icon {...p}>
      <circle cx="12" cy="12" r="9" fill="var(--c-gold-bg)" />
      <circle cx="12" cy="12" r="9" />
      <path d="M9 9h4.5a2 2 0 1 1 0 4H9m0 0h4.5a2 2 0 1 1 0 4H9m0-8v8m3-10v2m0 8v2" />
    </Icon>
  ),
  flame: (p: P = {}) => (
    <Icon {...p}>
      <path d="M12 2c1 4 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3-1-3 1-6 1-9z" fill="currentColor" stroke="none" />
    </Icon>
  ),
  refresh: (p: P = {}) => (
    <Icon {...p}>
      <path d="M4 12a8 8 0 0 1 14-5l2-2v6h-6l3-3" />
      <path d="M20 12a8 8 0 0 1-14 5l-2 2v-6h6l-3 3" />
    </Icon>
  ),
  trend: (p: P = {}) => (
    <Icon {...p}>
      <polyline points="3 17 9 11 13 15 21 7" />
      <polyline points="15 7 21 7 21 13" />
    </Icon>
  ),
  filter: (p: P = {}) => (
    <Icon {...p}>
      <polygon points="3 4 21 4 14 13 14 19 10 21 10 13 3 4" />
    </Icon>
  ),
  trash: (p: P = {}) => (
    <Icon {...p}>
      <polyline points="4 7 20 7" />
      <path d="M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13" />
      <path d="M9 7V4h6v3" />
    </Icon>
  ),
  more: (p: P = {}) => (
    <Icon {...p}>
      <circle cx="6" cy="12" r="1.4" fill="currentColor" />
      <circle cx="12" cy="12" r="1.4" fill="currentColor" />
      <circle cx="18" cy="12" r="1.4" fill="currentColor" />
    </Icon>
  ),
  google: ({ size = 16 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{ flex: 'none' }}>
      <path
        fill="#4285F4"
        d="M22.5 12.27c0-.79-.07-1.55-.2-2.27H12v4.51h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.75h3.57c2.08-1.92 3.28-4.74 3.28-8.3z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.75c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.15-4.53H2.18v2.84A11 11 0 0 0 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.85 14.12A6.6 6.6 0 0 1 5.5 12c0-.74.13-1.45.35-2.12V7.04H2.18A11 11 0 0 0 1 12c0 1.78.43 3.46 1.18 4.96z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1A11 11 0 0 0 2.18 7.04l3.67 2.84C6.71 7.31 9.14 5.38 12 5.38z"
      />
    </svg>
  ),
};
