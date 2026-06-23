import { Hanken_Grotesk, JetBrains_Mono } from "next/font/google";

// Display + body: a characterful grotesque (deliberately not Inter/Space Grotesk).
export const sans = Hanken_Grotesk({
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
});

// All data, metrics, IDs, signatures, code — the console's technical voice.
export const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "700"],
  variable: "--font-mono",
});
