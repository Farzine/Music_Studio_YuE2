import type { Metadata } from "next";

import { AppShell } from "@/components/app-shell";
import { Providers } from "@/app/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "YuE2 Music Studio",
  description: "Local-first AI music creation with the open YuE2-3B model.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
