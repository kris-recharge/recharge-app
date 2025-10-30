/** @type {import('next').NextConfig} */
const nextConfig = {
  async redirects() {
    return [
      {
        source: '/',
        destination: '/login',
        permanent: false, // temporary redirect (307)
      },
    ];
  },
};

module.exports = nextConfig;