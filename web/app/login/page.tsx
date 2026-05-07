import { signIn, auth } from '@/auth';
import { redirect } from 'next/navigation';
import { Btn, CSLogo } from '@/components/ui';
import { Ic } from '@/components/icons';

export default async function LoginPage({
  searchParams,
}: {
  searchParams?: Promise<{ next?: string }>;
}) {
  // If already signed in, bounce home (or to ?next=... if provided)
  const session = await auth();
  const params = await (searchParams ?? Promise.resolve({}));
  const nextUrl = params?.next ?? '/generate';
  if (session?.user) redirect(nextUrl);

  async function googleSignIn() {
    'use server';
    await signIn('google', { redirectTo: nextUrl });
  }

  return (
    <main
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1.1fr',
        minHeight: '100vh',
      }}
    >
      {/* Form side */}
      <section
        style={{
          padding: '48px 56px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          background: 'var(--c-bg)',
        }}
      >
        <div style={{ maxWidth: 360, width: '100%', margin: '0 auto' }}>
          <h1
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 40,
              fontWeight: 400,
              letterSpacing: '-0.02em',
              margin: '0 0 8px',
              color: 'var(--c-ink)',
            }}
          >
            Welcome back.
          </h1>
          <p style={{ fontSize: 14, color: 'var(--c-ink-3)', margin: '0 0 28px' }}>
            Sign in to continue to your library. 5 cheatsheets free, no card.
          </p>

          <form action={googleSignIn}>
            <Btn
              variant="secondary"
              size="lg"
              full
              icon={<Ic.google size={16} />}
              type="submit"
            >
              Continue with Google
            </Btn>
          </form>

          <p
            style={{
              fontSize: 12.5,
              color: 'var(--c-ink-3)',
              textAlign: 'center',
              marginTop: 24,
              lineHeight: 1.5,
            }}
          >
            By continuing you agree to our{' '}
            <a href="#" style={{ color: 'var(--c-ink-2)', textDecoration: 'underline' }}>
              Terms
            </a>{' '}
            and{' '}
            <a href="#" style={{ color: 'var(--c-ink-2)', textDecoration: 'underline' }}>
              Privacy Policy
            </a>
            .
          </p>
        </div>
      </section>

      {/* Editorial side */}
      <section
        style={{
          background: 'var(--c-ink)',
          color: 'var(--c-bg)',
          padding: '48px 56px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        <CSLogo size={18} color="#faf8f3" />
        <div style={{ position: 'relative', zIndex: 1 }}>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: '#e8a583',
              letterSpacing: '.1em',
              marginBottom: 18,
            }}
          >
            NEW · BOOK NOTES
          </div>
          <h2
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 56,
              lineHeight: 1,
              fontWeight: 400,
              letterSpacing: '-0.02em',
              margin: '0 0 20px',
            }}
          >
            Your lectures,
            <br />
            <span style={{ fontStyle: 'italic', color: '#e8a583' }}>distilled.</span>
          </h2>
          <p
            style={{
              fontSize: 15,
              color: '#b8b0a6',
              maxWidth: 380,
              lineHeight: 1.55,
            }}
          >
            Paste a YouTube link, get a clean cheatsheet or full chapter-by-chapter
            book notes.
          </p>
        </div>
        <div
          style={{
            display: 'flex',
            gap: 16,
            fontSize: 12,
            color: '#807972',
            fontFamily: 'var(--font-mono)',
          }}
        >
          <span>● secure auth</span>
          <span>● refund-on-fail</span>
          <span>● your data, your library</span>
        </div>
        <div
          style={{
            position: 'absolute',
            bottom: -80,
            right: -80,
            width: 280,
            height: 280,
            borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(201,87,43,.18), transparent 70%)',
          }}
        />
      </section>
    </main>
  );
}
