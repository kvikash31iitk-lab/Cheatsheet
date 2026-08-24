import { NextResponse } from 'next/server';
import { auth } from '@/auth';

const PROTECTED_PREFIXES = [
  '/generate',
  '/new',
  '/library',
  '/dashboard',
  '/wallet',
  '/admin',
];

function adminEmails(): string[] {
  const raw = process.env.ADMIN_EMAILS ?? '';
  return raw
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

function isLocalDesktop(req: any): boolean {
  const host = req.headers.get('host') || '';
  return (
    host.includes('localhost') ||
    host.includes('127.0.0.1') ||
    process.env.DESKTOP_MODE === '1'
  );
}

export default auth((req) => {
  const path = req.nextUrl.pathname;
  const isLocal = isLocalDesktop(req);

  // 1. /api/* requests forwarded to FastAPI: inject X-User-ID and the shared secret
  if (path.startsWith('/api/')) {
    const headers = new Headers(req.headers);
    const userId = req.auth?.user?.id || (isLocal ? 'local-user' : undefined);
    if (userId) {
      headers.set('X-User-ID', userId);
      headers.set('X-Internal-Token', process.env.INTERNAL_API_TOKEN ?? '');
    }
    return NextResponse.next({ request: { headers } });
  }

  // Local Desktop mode: zero login required!
  if (isLocal) {
    if (path === '/login' || path === '/') {
      return NextResponse.redirect(new URL('/generate', req.url));
    }
    return NextResponse.next();
  }

  // 2. Protected app pages: bounce to /login when no session (production only)
  if (!req.auth && PROTECTED_PREFIXES.some((p) => path.startsWith(p))) {
    const url = new URL('/login', req.url);
    url.searchParams.set('next', path);
    return NextResponse.redirect(url);
  }

  // 3. /admin: signed in but not in the ADMIN_EMAILS list -> bounce to /dashboard.
  if (path.startsWith('/admin') && req.auth) {
    const email = req.auth.user?.email?.toLowerCase();
    if (!email || !adminEmails().includes(email)) {
      return NextResponse.redirect(new URL('/dashboard', req.url));
    }
  }
});

export const config = {
  matcher: [
    /*
     * Run on everything except:
     *  - auth/*       — Auth.js's own handler routes.
     *  - _next/static, _next/image — Next internals
     *  - favicon.ico, robots.txt   — static assets
     */
    '/((?!auth/|_next/static|_next/image|favicon.ico|robots.txt).*)',
  ],
};
