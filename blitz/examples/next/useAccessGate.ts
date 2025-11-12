import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export function useAccessGate() {
  const router = useRouter();
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const ok = window.localStorage.getItem('blitz_access') === 'true';
    if (!ok) router.replace('/access');
  }, [router]);
}

