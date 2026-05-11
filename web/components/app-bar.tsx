'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useSession, signOut } from 'next-auth/react';
import { CSLogo, Btn } from '@/components/ui';
import { getMe, type Me } from '@/lib/api';

function Avatar({
  src,
  name,
}: {
  src?: string | null;
  name?: string | null;
}) {
  const initial = (name ?? '?').trim().charAt(0).toUpperCase();
  return (
    <div
      style={{
        width: 32,
        height: 32,
        borderRadius: '50%',
        background: 'var(--c-violet-bg)',
        color: 'var(--c-violet)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontWeight: 600,
        fontSize: 13,
        overflow: 'hidden',
      }}
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={name ?? 'avatar'}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      ) : (
        initial
      )}
    </div>
  );
}

export function AppBar() {
  const { data: session, status } = useSession();
  const user = session?.user;
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    if (status === 'authenticated') {
      getMe()
        .then(setMe)
        .catch(() => undefined);
    }
  }, [status]);

  return (
    <>
      {me?.banner && (
        <div
          style={{
            background: 'var(--c-gold-bg)',
            color: 'var(--c-gold)',
            padding: '10px 56px',
            fontSize: 13,
            borderBottom: '1px solid var(--c-line)',
          }}
        >
          <strong>{me.banner.title}</strong>
          <span style={{ marginLeft: 8 }}>{me.banner.body}</span>
        </div>
      )}
      {me?.maintenance?.active && (
        <div
          style={{
            background: 'var(--c-error-bg)',
            color: 'var(--c-error)',
            padding: '10px 56px',
            fontSize: 13,
            borderBottom: '1px solid var(--c-line)',
          }}
        >
          ⚠ Maintenance mode: {me.maintenance.message}
        </div>
      )}
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
        <nav
          style={{
            display: 'flex',
            gap: 16,
            fontSize: 13,
            color: 'var(--c-ink-3)',
            alignItems: 'center',
          }}
        >
          {status === 'loading' ? null : user ? (
            <>
              <Link href="/dashboard" style={{ color: 'inherit', textDecoration: 'none' }}>
                Dashboard
              </Link>
              <Link href="/generate" style={{ color: 'inherit', textDecoration: 'none' }}>
                Generate
              </Link>
              <Link href="/library" style={{ color: 'inherit', textDecoration: 'none' }}>
                Library
              </Link>
              <Link href="/wallet" style={{ color: 'inherit', textDecoration: 'none' }}>
                Wallet
              </Link>
              {me?.is_admin && (
                <Link
                  href="/admin"
                  style={{
                    color: 'var(--c-accent)',
                    textDecoration: 'none',
                    fontWeight: 500,
                  }}
                >
                  Admin
                </Link>
              )}
              <span style={{ color: 'var(--c-line-2)' }}>·</span>
              <Avatar src={user.image} name={user.name} />
              <Btn variant="ghost" size="sm" onClick={() => signOut({ callbackUrl: '/' })}>
                Sign out
              </Btn>
            </>
          ) : (
            <>
              <Link href="/" style={{ color: 'inherit', textDecoration: 'none' }}>
                Home
              </Link>
              <Link href="/login" style={{ textDecoration: 'none' }}>
                <Btn variant="primary" size="sm">
                  Sign in
                </Btn>
              </Link>
            </>
          )}
        </nav>
      </header>
    </>
  );
}
