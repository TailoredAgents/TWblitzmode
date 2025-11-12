// Next.js 15.5 Configuration for VouchLink AI Corporate Dashboard
// September 2025 AI Integration with Turbopack and Node.js Middleware

/** @type {import('next').NextConfig} */
const path = require('path');

const nextConfig = {
  // Enable React Strict Mode for development and production
  reactStrictMode: true,

  // Enable experimental features for Next.js 15.5
  experimental: {
    // Leave empty for stable features
  },

  // Production optimizations
  compress: true,
  poweredByHeader: false,

  // Image optimization
  images: {
    formats: ['image/avif', 'image/webp'],
    minimumCacheTTL: 60,
  },

  // Environment variables
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8888',
    NEXT_PUBLIC_WEBSOCKET_URL: process.env.NEXT_PUBLIC_WEBSOCKET_URL || 'http://localhost:8888',
  },

  // API proxying for development
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8888'}/api/:path*`,
      },
    ];
  },

  // Security headers
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          {
            key: 'X-Frame-Options',
            value: 'DENY',
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
          {
            key: 'Referrer-Policy',
            value: 'strict-origin-when-cross-origin',
          },
        ],
      },
    ];
  },

  // Bundle analysis
  webpack: (config, { dev, isServer }) => {
    // Ensure alias resolution for '@/…' imports across environments
    config.resolve = config.resolve || {};
    config.resolve.alias = {
      ...(config.resolve.alias || {}),
      '@': path.resolve(__dirname, 'src'),
    };

    // Enable source maps in development
    if (dev) {
      config.devtool = 'eval-source-map';
    }

    // Optimize for performance
    if (!dev && !isServer) {
      config.optimization.splitChunks.cacheGroups = {
        ...config.optimization.splitChunks.cacheGroups,
        vendor: {
          test: /[\\/]node_modules[\\/]/,
          name: 'vendors',
          chunks: 'all',
        },
      };
    }

    return config;
  },
};

module.exports = nextConfig;
