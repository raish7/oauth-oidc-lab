import type { NextConfig } from "next";

// Deliberately no rewrites or proxying: the browser talks to the BFF on its own
// origin so CORS and cross-origin cookies are real, the way they are in production.
const nextConfig: NextConfig = {
  reactStrictMode: true,
};

export default nextConfig;
