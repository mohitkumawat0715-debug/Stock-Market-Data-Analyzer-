import { TickerAnalysis } from "@/components/TickerAnalysis";

export default async function TickerPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  return <TickerAnalysis symbol={decodeURIComponent(symbol).toUpperCase()} />;
}
