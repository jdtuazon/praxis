import type { Metadata } from "next";
import { mono, sans } from "./fonts";
import "./globals.css";
import { Shell } from "@/components/Shell";

export const metadata: Metadata = {
  title: "Praxis",
  description:
    "A self-improving agent that turns natural-language instructions into Linear actions, synthesizes new capabilities at runtime, and measurably improves with use.",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
