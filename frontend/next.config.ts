import type { NextConfig } from "next";

/**
 * In production the API is reached through a same-origin `/api` rewrite
 * declared in `vercel.json`. Development used to point the browser straight at
 * `http://127.0.0.1:8000` instead, which made every request cross-origin — and
 * the session refresh cookie is `SameSite` and un-`Secure` over plain HTTP, so
 * it never travelled. The effect was that any full page load in development
 * dropped you back at the sign-in screen, while client-side navigation
 * appeared to work fine.
 *
 * Proxying `/api` in development too makes both environments same-origin, so
 * sessions survive a reload and the code path under test is the one that ships.
 */
const nextConfig: NextConfig = {
  async rewrites() {
    if (process.env.NODE_ENV === "production") return [];
    const backend = process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
