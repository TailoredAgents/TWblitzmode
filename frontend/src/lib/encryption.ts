/**
 * Client-side encryption utilities for sensitive data
 * Uses Web Crypto API for secure encryption before transmission
 */

// Generate a random encryption key
export async function generateKey(): Promise<CryptoKey> {
  return await crypto.subtle.generateKey(
    {
      name: 'AES-GCM',
      length: 256,
    },
    true,
    ['encrypt', 'decrypt']
  );
}

// Encrypt data using AES-GCM
export async function encryptData(data: string, key: CryptoKey): Promise<{ encrypted: string; iv: string }> {
  const encoder = new TextEncoder();
  const dataBuffer = encoder.encode(data);

  // Generate a random initialization vector
  const iv = crypto.getRandomValues(new Uint8Array(12));

  const encryptedBuffer = await crypto.subtle.encrypt(
    {
      name: 'AES-GCM',
      iv: iv,
    },
    key,
    dataBuffer
  );

  // Convert to base64 for transmission
  const encrypted = btoa(String.fromCharCode(...new Uint8Array(encryptedBuffer)));
  const ivBase64 = btoa(String.fromCharCode(...iv));

  return { encrypted, iv: ivBase64 };
}

// Export key to base64 for server-side decryption
export async function exportKey(key: CryptoKey): Promise<string> {
  const exported = await crypto.subtle.exportKey('raw', key);
  return btoa(String.fromCharCode(...new Uint8Array(exported)));
}

// Encrypt sensitive cookies before transmission
export async function encryptCookies(cookies: {
  li_at: string;
  jsessionid?: string;
  user_agent?: string;
}): Promise<{
  encrypted_payload: string;
  encryption_key: string;
  iv: string;
}> {
  // Generate a new key for this session
  const key = await generateKey();

  // Serialize the cookie data
  const cookieData = JSON.stringify(cookies);

  // Encrypt the data
  const { encrypted, iv } = await encryptData(cookieData, key);

  // Export the key for server-side decryption
  const exportedKey = await exportKey(key);

  return {
    encrypted_payload: encrypted,
    encryption_key: exportedKey,
    iv: iv,
  };
}

/**
 * Validates that the browser supports Web Crypto API
 */
export function isEncryptionSupported(): boolean {
  return typeof crypto !== 'undefined' &&
    typeof crypto.subtle?.generateKey === 'function';
}
