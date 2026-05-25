/** @type {import('next').NextConfig} */
const API_BASE = process.env.INTERNAL_API_BASE || 'http://127.0.0.1:8000';

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${API_BASE}/api/:path*` },
    ];
  },
  experimental: {
    serverActions: {
      allowedOrigins: [
        'cheetsheet.tech',
        'cheetsheet.tech.',
        'www.cheetsheet.tech',
        'cheat.rivanair.in',
      ],
    },
  },
};

module.exports = nextConfig;
