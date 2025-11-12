import { apiService } from '../services/api';
import { clearAccessToken } from './authToken';

const DEFAULT_LOGOUT_TIMEOUT_MS = 5000;

/**
 * Perform a logout request with a defensive timeout and client-side cleanup.
 * Clears the cached access token and forces navigation back to the login page.
 */
export async function performLogout(timeoutMs: number = DEFAULT_LOGOUT_TIMEOUT_MS): Promise<void> {
  try {
    await Promise.race([
      apiService.logout(),
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error('Logout timeout')), Math.max(timeoutMs, 0)),
      ),
    ]);
  } catch (error) {
    console.warn('[logout] Logout request failed', error);
  } finally {
    clearAccessToken();
    if (typeof window !== 'undefined') {
      try {
        window.location.replace('/login');
      } catch (navigationError) {
        console.warn('[logout] Fallback navigation triggered', navigationError);
        window.location.href = '/login';
      }
    }
  }
}

export default performLogout;
