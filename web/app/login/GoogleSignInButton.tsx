'use client';

import { signIn } from 'next-auth/react';
import { Btn } from '@/components/ui';
import { Ic } from '@/components/icons';

export function GoogleSignInButton({ callbackUrl }: { callbackUrl: string }) {
  return (
    <Btn
      variant="secondary"
      size="lg"
      full
      icon={<Ic.google size={16} />}
      onClick={() => signIn('google', { callbackUrl })}
    >
      Continue with Google
    </Btn>
  );
}
