import NextAuth from 'next-auth';
import Google from 'next-auth/providers/google';

const INTERNAL_API_BASE = process.env.INTERNAL_API_BASE ?? 'http://127.0.0.1:8000';

export const { auth, handlers, signIn, signOut } = NextAuth({
  basePath: '/auth',
  providers: [
    Google({
      clientId: process.env.AUTH_GOOGLE_ID,
      clientSecret: process.env.AUTH_GOOGLE_SECRET,
    }),
  ],
  pages: { signIn: '/login' },
  session: { strategy: 'jwt' },
  callbacks: {
    async signIn({ user, account }) {
      if (!user.email) return false;
      try {
        const r = await fetch(`${INTERNAL_API_BASE}/api/auth/upsert-user`, {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            'X-Internal-Token': process.env.INTERNAL_API_TOKEN ?? '',
          },
          body: JSON.stringify({
            email: user.email,
            name: user.name,
            picture_url: user.image,
            google_sub: account?.providerAccountId,
          }),
        });
        if (!r.ok) {
          console.error('upsert-user failed', r.status, await r.text());
          return false;
        }
        const data = (await r.json()) as { id: string };
        (user as { id?: string }).id = data.id;
        return true;
      } catch (e) {
        console.error('upsert-user threw', e);
        return false;
      }
    },
    async jwt({ token, user }) {
      if (user && (user as { id?: string }).id) {
        token.userId = (user as { id: string }).id;
      }
      return token;
    },
    async session({ session, token }) {
      if (token.userId && session.user) {
        (session.user as { id?: string }).id = token.userId as string;
      }
      return session;
    },
  },
});
