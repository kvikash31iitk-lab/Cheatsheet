import { NextResponse } from 'next/server';
import { auth } from '@/auth';

const PROTECTED_PREFIXES = [
  '/generate',
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

export default auth((req) => {
  const path = req.nextUrl.pathname;

  // /api/* requests forwarded to FastAPI: inject X-User-ID and the shared
  // secret if the user is signed in. NextAuth lives at /auth/* (separate
  // basePath) so there's no clash here.
  if (path.startsWith('/api/')) {
    const headers = new Headers(req.headers);
    const userId = req.auth?.user?.id;
    if (userId) {
      headers.set('X-User-ID', userId);
      headers.set('X-Internal-Token', process.env.INTERNAL_API_TOKEN ?? '');
    }
    return NextResponse.next({ request: { headers } });
  }

  // 2. Protected app pages: bounce to /login when no session.
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
     *  - _next/static, _next/image (Next internals)
     *  - favicon.ico, robots.txt, etc.
     */
    '/((?!_next/static|_next/image|favicon.ico|robots.txt).*)',
  ],
};
