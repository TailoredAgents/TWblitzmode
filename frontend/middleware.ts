import { NextResponse, type NextRequest } from 'next/server';

/**
 * Developer portal middleware retired in Wave 1.
 * Keeping a no-op handler ensures Next.js middleware plumbing remains valid.
 */
export function middleware(_request: NextRequest) {
  return NextResponse.next();
}

export const config = {
  matcher: [],
};
