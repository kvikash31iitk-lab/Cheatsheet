import Link from 'next/link';
import { CSLogo } from '@/components/ui';

export const AppBar = () => (
  <header
    style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '20px 56px',
      borderBottom: '1px solid var(--c-line)',
    }}
  >
    <Link href="/" style={{ textDecoration: 'none' }}>
      <CSLogo size={18} />
    </Link>
    <nav style={{ display: 'flex', gap: 18, fontSize: 13, color: 'var(--c-ink-3)' }}>
      <Link href="/" style={{ color: 'inherit', textDecoration: 'none' }}>
        Home
      </Link>
      <span>·</span>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>Phase 0 · no auth</span>
    </nav>
  </header>
);
