import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone", // web/Dockerfile copies .next/standalone into a small runtime image
};

export default nextConfig;
