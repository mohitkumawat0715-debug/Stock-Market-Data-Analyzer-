import type { Metadata } from "next";
import { Frame, Disclaimer } from "@/components/Frame";
import "./globals.css";

export const metadata: Metadata = {
  title: "Market/Lab — Stock Market Data Analyzer",
  description: "Educational market data analysis, technical indicators, and strategy simulations.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Frame>
          <Disclaimer />
          {children}
        </Frame>
      </body>
    </html>
  );
}
