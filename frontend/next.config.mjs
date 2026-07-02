/** @type {import('next').NextConfig} */
const nextConfig = {
  env: {
    NEXT_PUBLIC_AUTH_REQUIRED:
      process.env.NEXT_PUBLIC_AUTH_REQUIRED ?? (process.env.VERCEL ? "false" : "true"),
  },
  reactStrictMode: true,
  output: "standalone",
};

export default nextConfig;
