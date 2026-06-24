import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    typedRoutes: false,
  },
  images: {
    remotePatterns: [],
  },
};

export default nextConfig;
