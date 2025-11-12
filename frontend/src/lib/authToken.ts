let accessToken: string | null = null;
let hasInitialized = false;

// Initialize from localStorage once on first access
function initializeToken(): void {
  const storage = typeof window !== 'undefined' ? window.localStorage : undefined;
  if (!hasInitialized && storage) {
    const storedToken = storage.getItem('access_token');
    if (storedToken) {
      accessToken = storedToken;
    }
    hasInitialized = true;
  }
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  hasInitialized = true;

  const storage = typeof window !== 'undefined' ? window.localStorage : undefined;
  if (storage) {
    if (token) {
      storage.setItem('access_token', token);
    } else {
      storage.removeItem('access_token');
    }
  }
}

export function getAccessToken(): string | null {
  initializeToken();
  return accessToken;
}

export function clearAccessToken(): void {
  accessToken = null;
  hasInitialized = true;
  // Also clear from localStorage
  const storage = typeof window !== 'undefined' ? window.localStorage : undefined;
  if (storage) {
    storage.removeItem('access_token');
  }
}

export function hasAccessToken(): boolean {
  const token = getAccessToken();
  return token !== null && token !== '';
}
