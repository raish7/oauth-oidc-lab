import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OAuth lab",
  description: "Hands-on OAuth 2.0 / OIDC lab frontend",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
