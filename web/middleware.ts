import { NextResponse } from 'next/server';
import { auth } from '@/auth';

const PROTECTED_PREFIXES = ['/generate', '/library', '/dashboard', '/wallet'];

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
