const backendOrigin =
  process.env.INTERNAL_API_ORIGIN ?? 'http://localhost:8000';

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  async rewrites() {
    return {
      beforeFiles: [
        // NextAuth API routes — handled by Next.js, not proxied to backend
        {
          source: '/api/auth/:path*',
          destination: '/api/auth/:path*',
        },
      ],
      fallback: [
        // All other API routes — proxy to FastAPI backend
        {
          source: '/api/:path*',
          destination: `${backendOrigin}/api/:path*`,
        },
      ],
    };
  },
};

export default nextConfig;
