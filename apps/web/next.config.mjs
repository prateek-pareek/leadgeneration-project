/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  experimental: {
    typedRoutes: false,
  },
  images: {
    remotePatterns: [],
  },
};

export default nextConfig;
