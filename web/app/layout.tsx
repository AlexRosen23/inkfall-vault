import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Shell } from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "The Inkfall Vault",
  description: "Permission-aware document evidence workbench over fictional legal, finance and policy documents.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#141518",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
