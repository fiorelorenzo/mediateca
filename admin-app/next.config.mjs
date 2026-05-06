/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  experimental: { ppr: false },
  webpack: (config) => {
    config.externals.push({
      "node:crypto": "crypto",
    });
    return config;
  },
};

export default nextConfig;
