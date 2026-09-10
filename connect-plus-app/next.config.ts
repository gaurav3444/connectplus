import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The floating "N" badge is Next's dev-only route indicator, not part of the
  // app — it sits over the bottom-left of every screen while reviewing designs.
  devIndicators: false,
};

export default nextConfig;
