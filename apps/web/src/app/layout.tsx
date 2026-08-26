import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "ReclaimRail | Merchant Recovery Command Center",
  description:
    "Incident-aware, policy-bounded payment recovery control plane.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}