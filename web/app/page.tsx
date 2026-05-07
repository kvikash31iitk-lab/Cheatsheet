import Link from 'next/link';
import { Btn, Tag, CSLogo } from '@/components/ui';
import { Ic } from '@/components/icons';

const NavBar = () => (
  <header
    style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '20px 56px',
      borderBottom: '1px solid var(--c-line)',
    }}
  >
    <CSLogo size={18} />
    <nav style={{ display: 'flex', gap: 32, fontSize: 13.5, color: 'var(--c-ink-2)' }}>
      <a href="#features" style={{ textDecoration: 'none', color: 'inherit' }}>Features</a>
      <a href="#pricing" style={{ textDecoration: 'none', color: 'inherit' }}>Pricing</a>
      <a href="#how" style={{ textDecoration: 'none', color: 'inherit' }}>How it works</a>
      <a href="#faq" style={{ textDecoration: 'none', color: 'inherit' }}>FAQ</a>
    </nav>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      <Link href="/login" style={{ textDecoration: 'none' }}>
        <Btn variant="ghost" size="md">Log in</Btn>
      </Link>
      <Link href="/generate" style={{ textDecoration: 'none' }}>
        <Btn variant="primary" size="md">Try free</Btn>
      </Link>
    </div>
  </header>
);

const Hero = () => (
  <section style={{ padding: '72px 56px 56px', textAlign: 'center', position: 'relative' }}>
    <Tag tone="accent" style={{ marginBottom: 24, padding: '5px 12px' }}>
      <Ic.sparkle size={11} /> New · Book Notes for long lectures
    </Tag>
    <h1
      style={{
        fontFamily: 'var(--font-serif)',
        fontSize: 88,
        lineHeight: 0.98,
        fontWeight: 400,
        letterSpacing: '-0.025em',
        margin: '0 auto 28px',
        maxWidth: 920,
        color: 'var(--c-ink)',
      }}
    >
      Turn any YouTube video<br />
      into <span style={{ fontStyle: 'italic', color: 'var(--c-accent)' }}>study-ready</span> notes.
    </h1>
    <p
      style={{
        fontSize: 19,
        lineHeight: 1.5,
        color: 'var(--c-ink-2)',
        maxWidth: 600,
        margin: '0 auto 36px',
      }}
    >
      Paste a link. Get a clean cheatsheet or a full set of book-style notes — formatted, downloadable,
      and built for how students actually study.
    </p>
    <div style={{ display: 'flex', gap: 10, justifyContent: 'center', marginBottom: 14 }}>
      <Link href="/generate" style={{ textDecoration: 'none' }}>
        <Btn variant="primary" size="xl" iconRight={<Ic.arrow size={16} />}>
          Start free — 5 cheatsheets
        </Btn>
      </Link>
      <Btn variant="secondary" size="xl" icon={<Ic.play size={13} />}>
        Watch demo · 90s
      </Btn>
    </div>
    <div style={{ fontSize: 12.5, color: 'var(--c-ink-3)' }}>
      No credit card · 5 cheatsheets + 2 book notes free · Pay only for what you use
    </div>
  </section>
);

const FeatureSplit = () => (
  <section
    id="features"
    style={{
      padding: '80px 56px',
      background: 'var(--c-surface-2)',
      borderTop: '1px solid var(--c-line)',
    }}
  >
    <div style={{ textAlign: 'center', marginBottom: 48 }}>
      <Tag tone="neutral" style={{ marginBottom: 16 }}>
        Two formats. Built for how you study.
      </Tag>
      <h2
        style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 56,
          fontWeight: 400,
          letterSpacing: '-0.02em',
          margin: '0 0 12px',
          color: 'var(--c-ink)',
        }}
      >
        One tool, <span style={{ fontStyle: 'italic' }}>two flavours</span> of notes.
      </h2>
      <p style={{ fontSize: 16, color: 'var(--c-ink-2)', maxWidth: 560, margin: '0 auto' }}>
        Pick what fits the moment — a quick cheatsheet before an exam, or a deep set of book notes
        for the whole semester.
      </p>
    </div>

    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 20,
        maxWidth: 1100,
        margin: '0 auto',
      }}
    >
      <div
        style={{
          background: 'var(--c-surface)',
          borderRadius: 20,
          padding: 32,
          border: '1px solid var(--c-line)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              background: 'var(--c-accent-2)',
              color: 'var(--c-accent)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Ic.zap size={18} />
          </div>
          <div>
            <div style={{ fontSize: 18, fontWeight: 600, color: 'var(--c-ink)' }}>Cheatsheet</div>
            <div style={{ fontSize: 12.5, color: 'var(--c-ink-3)' }}>~15 seconds · 1 page</div>
          </div>
        </div>
        <p style={{ fontSize: 14, color: 'var(--c-ink-2)', lineHeight: 1.55, marginBottom: 20 }}>
          A dense, scannable single page. Key terms, formulas, and the 5-second answer to "what is
          this video about?"
        </p>
        <div
          style={{
            background: 'var(--c-surface-2)',
            borderRadius: 12,
            padding: 16,
            fontSize: 11,
            lineHeight: 1.5,
            color: 'var(--c-ink-2)',
          }}
        >
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 16, color: 'var(--c-ink)', marginBottom: 8 }}>
            Photosynthesis
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <div><b style={{ color: 'var(--c-ink)' }}>Inputs:</b> CO₂, H₂O, light</div>
            <div><b style={{ color: 'var(--c-ink)' }}>Outputs:</b> C₆H₁₂O₆, O₂</div>
            <div><b style={{ color: 'var(--c-ink)' }}>Site:</b> chloroplasts</div>
            <div><b style={{ color: 'var(--c-ink)' }}>Phases:</b> light, Calvin</div>
          </div>
          <div
            style={{
              marginTop: 10,
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              background: '#fff',
              padding: 6,
              borderRadius: 6,
            }}
          >
            6CO₂ + 6H₂O → C₆H₁₂O₆ + 6O₂
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 18, flexWrap: 'wrap' }}>
          {['Exam crunch', 'Lecture review', 'Quick recall'].map((t) => (
            <Tag key={t} tone="accent">{t}</Tag>
          ))}
        </div>
      </div>

      <div style={{ background: 'var(--c-ink)', color: 'var(--c-bg)', borderRadius: 20, padding: 32 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              background: 'rgba(201,87,43,.2)',
              color: '#e8a583',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Ic.book size={18} />
          </div>
          <div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>Book Notes</div>
            <div style={{ fontSize: 12.5, color: '#b8b0a6' }}>~45 seconds · multi-chapter</div>
          </div>
        </div>
        <p style={{ fontSize: 14, color: '#d6cfc4', lineHeight: 1.55, marginBottom: 20 }}>
          Full chapter-by-chapter notes with examples, derivations, and key takeaways. Like a
          textbook adapted from the lecture.
        </p>
        <div
          style={{
            background: 'rgba(255,255,255,0.04)',
            borderRadius: 12,
            padding: 16,
            fontSize: 11,
            lineHeight: 1.5,
            color: '#d6cfc4',
          }}
        >
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 16, color: '#fff', marginBottom: 4 }}>
            Chapter 3 · Calvin Cycle
          </div>
          <div style={{ fontSize: 10, color: '#b8b0a6', marginBottom: 8 }}>
            3.1 Carbon fixation · 3.2 Reduction · 3.3 Regeneration
          </div>
          <p style={{ margin: 0 }}>
            The Calvin cycle uses ATP and NADPH from the light reactions to fix carbon dioxide into
            glucose. Each turn fixes one CO₂; six turns produce one G3P sugar...
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 18, flexWrap: 'wrap' }}>
          {['Deep study', 'Semester prep', 'Reference doc'].map((t) => (
            <span
              key={t}
              style={{
                padding: '3px 8px',
                borderRadius: 999,
                fontSize: 11,
                background: 'rgba(255,255,255,.08)',
                color: '#d6cfc4',
              }}
            >
              {t}
            </span>
          ))}
        </div>
      </div>
    </div>
  </section>
);

const HowItWorks = () => {
  const steps = [
    {
      n: '01',
      t: 'Paste a YouTube link',
      d: 'Lecture, podcast, tutorial — anything with audio. We pull the transcript automatically.',
      icon: <Ic.link size={18} />,
    },
    {
      n: '02',
      t: 'See the cost upfront',
      d: 'We estimate tokens and rupees before you commit. No surprise charges, ever.',
      icon: <Ic.coin size={18} />,
    },
    {
      n: '03',
      t: 'Download & study',
      d: 'Your notes are ready in seconds. Export as PDF, Markdown, or plain text.',
      icon: <Ic.download size={18} />,
    },
  ];
  return (
    <section id="how" style={{ padding: '80px 56px' }}>
      <div style={{ textAlign: 'center', marginBottom: 56 }}>
        <h2
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 48,
            fontWeight: 400,
            letterSpacing: '-0.02em',
            margin: 0,
            color: 'var(--c-ink)',
          }}
        >
          Three steps. <span style={{ fontStyle: 'italic' }}>That's it.</span>
        </h2>
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 24,
          maxWidth: 1100,
          margin: '0 auto',
        }}
      >
        {steps.map((s) => (
          <div key={s.n} style={{ padding: 4 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  color: 'var(--c-ink-3)',
                  letterSpacing: '.08em',
                }}
              >
                {s.n}
              </span>
              <div style={{ flex: 1, height: 1, background: 'var(--c-line)' }} />
              <span style={{ color: 'var(--c-accent)' }}>{s.icon}</span>
            </div>
            <h3
              style={{
                fontFamily: 'var(--font-serif)',
                fontSize: 28,
                fontWeight: 400,
                margin: '0 0 8px',
                color: 'var(--c-ink)',
                letterSpacing: '-0.01em',
              }}
            >
              {s.t}
            </h3>
            <p style={{ fontSize: 14, lineHeight: 1.55, color: 'var(--c-ink-2)', margin: 0 }}>{s.d}</p>
          </div>
        ))}
      </div>
    </section>
  );
};

const Pricing = () => {
  const plans = [
    {
      name: 'Starter',
      price: '0',
      sub: 'Free, no card',
      highlight: false,
      items: ['5 cheatsheets free', '2 book notes free', 'Up to 30 min videos', 'PDF & Markdown export'],
    },
    {
      name: 'Top-up ₹200',
      price: '200',
      sub: '~25 cheatsheets',
      highlight: true,
      items: ['~25 cheatsheets', '~5 book notes', 'No video length limit', 'Priority queue'],
    },
    {
      name: 'Top-up ₹500',
      price: '500',
      sub: '~70 cheatsheets · save 12%',
      highlight: false,
      items: [
        '~70 cheatsheets',
        '~14 book notes',
        'No video length limit',
        'Priority queue + 2x history',
      ],
    },
  ];
  return (
    <section
      id="pricing"
      style={{
        padding: '80px 56px',
        background: 'var(--c-surface-2)',
        borderTop: '1px solid var(--c-line)',
      }}
    >
      <div style={{ textAlign: 'center', marginBottom: 48 }}>
        <Tag tone="mint" style={{ marginBottom: 16 }}>
          Pay for what you use · No subscriptions
        </Tag>
        <h2
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 48,
            fontWeight: 400,
            letterSpacing: '-0.02em',
            margin: '0 0 12px',
            color: 'var(--c-ink)',
          }}
        >
          Honest, <span style={{ fontStyle: 'italic' }}>transparent</span> pricing.
        </h2>
        <p style={{ fontSize: 15, color: 'var(--c-ink-2)', maxWidth: 540, margin: '0 auto' }}>
          Top up your wallet once. Spend per generation, see the exact cost before you confirm.
        </p>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 16,
          maxWidth: 1000,
          margin: '0 auto',
        }}
      >
        {plans.map((p) => (
          <div
            key={p.name}
            style={{
              background: p.highlight ? 'var(--c-ink)' : 'var(--c-surface)',
              color: p.highlight ? 'var(--c-bg)' : 'var(--c-ink)',
              borderRadius: 16,
              padding: 28,
              border: p.highlight ? 'none' : '1px solid var(--c-line)',
              position: 'relative',
            }}
          >
            {p.highlight && (
              <Tag tone="accent" style={{ position: 'absolute', top: -10, left: 24 }}>
                Most popular
              </Tag>
            )}
            <div
              style={{
                fontSize: 13,
                fontWeight: 500,
                color: p.highlight ? '#d6cfc4' : 'var(--c-ink-2)',
                marginBottom: 6,
              }}
            >
              {p.name}
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginBottom: 4 }}>
              <span
                style={{
                  fontFamily: 'var(--font-serif)',
                  fontSize: 56,
                  fontWeight: 400,
                  letterSpacing: '-0.02em',
                  lineHeight: 1,
                }}
              >
                ₹{p.price}
              </span>
            </div>
            <div
              style={{
                fontSize: 12.5,
                color: p.highlight ? '#b8b0a6' : 'var(--c-ink-3)',
                marginBottom: 22,
              }}
            >
              {p.sub}
            </div>
            <Btn variant={p.highlight ? 'accent' : 'secondary'} size="md" full>
              {p.price === '0' ? 'Start free' : 'Add credits'}
            </Btn>
            <div
              style={{
                height: 1,
                background: p.highlight ? 'rgba(255,255,255,.1)' : 'var(--c-line)',
                margin: '20px 0',
              }}
            />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
              {p.items.map((it, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    gap: 8,
                    fontSize: 13,
                    color: p.highlight ? '#d6cfc4' : 'var(--c-ink-2)',
                  }}
                >
                  <Ic.check size={14} />
                  {it}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
};

const FAQ = () => {
  const items = [
    {
      q: 'Which YouTube videos work?',
      a: 'Anything with auto-captions or English audio. Lectures, talks, tutorials, podcasts. We support up to 4-hour videos on paid plans.',
      open: true,
    },
    {
      q: 'How is this different from a YouTube summary?',
      a: 'Summaries compress. We expand. Cheatsheets are study-formatted with formulas, definitions, and structure. Book notes are full chapter-by-chapter writeups.',
    },
    {
      q: 'What happens if a generation fails?',
      a: 'You get a full automatic refund to your wallet within seconds. No tickets, no waiting.',
    },
    {
      q: 'Can I use this on my phone?',
      a: 'Yes — fully responsive, and we have a Telegram bot for one-tap generation while you watch.',
    },
    {
      q: 'Do you store my notes?',
      a: 'Yes, in your private library. You can delete anything anytime, and we never share your data.',
    },
  ];
  return (
    <section
      id="faq"
      style={{
        padding: '80px 56px',
        background: 'var(--c-surface-2)',
        borderTop: '1px solid var(--c-line)',
      }}
    >
      <div style={{ maxWidth: 720, margin: '0 auto' }}>
        <h2
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 44,
            fontWeight: 400,
            letterSpacing: '-0.02em',
            margin: '0 0 36px',
            color: 'var(--c-ink)',
            textAlign: 'center',
          }}
        >
          Frequently asked.
        </h2>
        <div
          style={{
            background: 'var(--c-surface)',
            borderRadius: 14,
            border: '1px solid var(--c-line)',
          }}
        >
          {items.map((it, i) => (
            <div
              key={i}
              style={{
                borderBottom: i < items.length - 1 ? '1px solid var(--c-line)' : 'none',
                padding: '18px 22px',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <span style={{ fontSize: 15, fontWeight: 500, color: 'var(--c-ink)' }}>{it.q}</span>
                {it.open ? <Ic.x size={14} /> : <Ic.plus size={14} />}
              </div>
              {it.open && (
                <p style={{ fontSize: 14, lineHeight: 1.55, color: 'var(--c-ink-2)', margin: '12px 0 0' }}>
                  {it.a}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};

const CtaBlock = () => (
  <section
    style={{
      padding: '96px 56px',
      textAlign: 'center',
      background: 'var(--c-ink)',
      color: 'var(--c-bg)',
    }}
  >
    <h2
      style={{
        fontFamily: 'var(--font-serif)',
        fontSize: 64,
        fontWeight: 400,
        letterSpacing: '-0.025em',
        margin: '0 0 20px',
        lineHeight: 1,
      }}
    >
      Stop rewriting lectures.
      <br />
      <span style={{ fontStyle: 'italic', color: '#e8a583' }}>Start studying.</span>
    </h2>
    <p style={{ fontSize: 16, color: '#b8b0a6', maxWidth: 480, margin: '0 auto 32px' }}>
      Your first 5 cheatsheets are on us. No card, no commitment.
    </p>
    <Link href="/generate" style={{ textDecoration: 'none' }}>
      <Btn variant="accent" size="xl" iconRight={<Ic.arrow size={16} />}>
        Try Cheatsheet free
      </Btn>
    </Link>
  </section>
);

const Footer = () => (
  <footer
    style={{
      padding: '40px 56px',
      borderTop: '1px solid var(--c-line)',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      fontSize: 12,
      color: 'var(--c-ink-3)',
    }}
  >
    <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
      <CSLogo size={14} />
      <span>© 2026 Cheatsheet Labs · Made for students</span>
    </div>
    <div style={{ display: 'flex', gap: 20 }}>
      <a href="#" style={{ color: 'inherit', textDecoration: 'none' }}>Privacy</a>
      <a href="#" style={{ color: 'inherit', textDecoration: 'none' }}>Terms</a>
      <a href="#" style={{ color: 'inherit', textDecoration: 'none' }}>Contact</a>
      <a href="#" style={{ color: 'inherit', textDecoration: 'none' }}>Telegram bot</a>
    </div>
  </footer>
);

export default function Page() {
  return (
    <main style={{ minHeight: '100vh' }}>
      <NavBar />
      <Hero />
      <FeatureSplit />
      <HowItWorks />
      <Pricing />
      <FAQ />
      <CtaBlock />
      <Footer />
    </main>
  );
}
