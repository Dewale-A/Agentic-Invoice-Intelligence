import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  env: {
    API_URL: process.env.API_URL || "http://35.171.2.221:8081",
  },
};

export default nextConfig;
