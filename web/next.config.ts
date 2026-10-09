import fs from "node:fs";
import path from "node:path";
import type { NextConfig } from "next";

/**
 * One .env for the whole repo (../.env). Next only reads web/.env*, so pull the
 * NEXT_PUBLIC_* values from the root file. Only browser-safe keys are picked up;
 * real environment variables win over the file.
 */
function rootPublicEnv(): Record<string, string> {
  const file = path.resolve(__dirname, "..", ".env");
  if (!fs.existsSync(file)) return {};
  const env: Record<string, string> = {};
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    const match = line.match(/^\s*(NEXT_PUBLIC_[A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (match) env[match[1]] = process.env[match[1]] ?? match[2];
  }
  return env;
}

const nextConfig: NextConfig = {
  env: rootPublicEnv(),
  async redirects() {
    return [{ source: "/portal", destination: "/portal/appointments", permanent: false }];
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
