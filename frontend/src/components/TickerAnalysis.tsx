"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, query } from "@/lib/api";
import { dateLabel, money, number, pct } from "@/lib/format";
import type { Indicators, Interval, Source } from "@/lib/types";
import { Card, Feedback, Metric, PageTitle, SelectField, TextField, Button } from "@/components/Frame";
import { IndicatorChart, PriceChart } from "@/components/Charts";

export function TickerAnalysis({ symbol }: { symbol: string }) {
  const [ticker, setTicker] = useState(symbol);
  const [source, setSource] = useState<Source>("csv");
  const [interval, setInterval] = useState<Interval>("1d");
  const [fast, setFast] = useState("10");
  const [slow, setSlow] = useState("30");
  const [showFast, setShowFast] = useState(true);
  const [showSlow, setShowSlow] = useState(true);
  const [showEma, setShowEma] = useState(false);
  const [data, setData] = useState<Indicators | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    setBusy(true);
    setError("");
    try {
      const path = "/indicators/" + encodeURIComponent(ticker.trim().toUpperCase()) +
        query({ source, interval, start_date: start, end_date: end, sma_fast: fast, sma_slow: slow });
      setData(await api<Indicators>(path));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Indicators could not be loaded.");
    } finally {
      setBusy(false);
    }
  }, [ticker, source, interval, start, end, fast, slow]);

  useEffect(() => { void load(); }, [load]);

  const bars = data?.bars || [];
  const last = bars[bars.length - 1];
  const latestSignal = [...bars].reverse().find((bar) => bar.signal === "BUY" || bar.signal === "SELL");
  const signalClass = latestSignal?.signal === "BUY" ? "positive" : latestSignal?.signal === "SELL" ? "negative" : "";

  return (
    <div className="page-stack">
      <PageTitle eyebrow="TECHNICAL ANALYSIS / 02" title={ticker.toUpperCase() + " under the hood."}
        description="Indicators and crossover signals are calculated by the backend on the selected bar interval." />
      <Card className="filter-card">
        <form className="filter-grid analysis-filters" onSubmit={load}>
          <TextField label="Ticker" value={ticker} onChange={setTicker} required />
          <SelectField label="Source" value={source} onChange={(value) => setSource(value as Source)}
            options={[["csv", "Offline CSV"], ["yahoo", "Yahoo history"]]} />
          <SelectField label="Interval" value={interval} onChange={(value) => setInterval(value as Interval)}
            options={[["1d", "Daily"], ["1wk", "Weekly"], ["1mo", "Monthly"]]} />
          <TextField label="Fast SMA" type="number" min={2} value={fast} onChange={setFast} required />
          <TextField label="Slow SMA" type="number" min={3} value={slow} onChange={setSlow} required />
          <TextField label="From" type="date" value={start} onChange={setStart} />
          <TextField label="To" type="date" value={end} onChange={setEnd} />
          <Button type="submit" disabled={busy}>{busy ? "Calculating…" : "Update analysis"}</Button>
        </form>
      </Card>
      {error ? <Feedback kind="error">{error}</Feedback> : null}
      {data && last ? (
        <>
          <div className="metric-grid">
            <Metric label="LAST CLOSE" value={money(last.close)} sub={dateLabel(last.timestamp)} />
            <Metric label="RSI" value={number(last.rsi)} sub={"Window " + data.parameters.rsi_window} />
            <Metric label="ROLLING VOLATILITY" value={pct(last.rolling_volatility)} sub={"Annualized · " + data.parameters.periods_per_year + " bars/year"} />
            <Metric label="LATEST CROSSOVER" value={latestSignal?.signal || "NONE"}
              sub={latestSignal ? dateLabel(latestSignal.timestamp) : "No crossover in selected range"} tone={signalClass} />
          </div>
          <Card title="Price, averages and volume" meta={data.metadata.ticker + " · " + interval}>
            <PriceChart bars={bars} overlays={[
              ...(showFast ? [{ label: "SMA fast", color: "#55d69f", values: bars.map((bar) => bar.sma_fast) }] : []),
              ...(showSlow ? [{ label: "SMA slow", color: "#f0bb68", values: bars.map((bar) => bar.sma_slow) }] : []),
              ...(showEma ? [{ label: "EMA", color: "#b29bff", values: bars.map((bar) => bar.ema) }] : []),
            ]} />
            <div className="chart-legend">
              <span className="legend-item"><i className="legend-green" /> Up bar</span>
              <span className="legend-item"><i className="legend-red" /> Down bar</span>
              <label className="legend-toggle"><input type="checkbox" checked={showFast} onChange={(event) => setShowFast(event.target.checked)} /> SMA {data.parameters.sma_fast_window}</label>
              <label className="legend-toggle"><input type="checkbox" checked={showSlow} onChange={(event) => setShowSlow(event.target.checked)} /> SMA {data.parameters.sma_slow_window}</label>
              <label className="legend-toggle"><input type="checkbox" checked={showEma} onChange={(event) => setShowEma(event.target.checked)} /> EMA {data.parameters.ema_window}</label>
            </div>
          </Card>
          <div className="indicator-grid">
            <Card title="Relative strength index" meta={"RSI " + data.parameters.rsi_window}>
              <IndicatorChart bars={bars} field="rsi" color="#a98bff" title="RSI" />
              <div className="chart-range"><span>Oversold guide 30</span><span>Overbought guide 70</span></div>
            </Card>
            <Card title="MACD" meta="Line and signal">
              <IndicatorChart bars={bars} field="macd_line" color="#59d5c4" title="MACD line" />
              <IndicatorChart bars={bars} field="macd_signal" color="#f1b85b" title="MACD signal" />
            </Card>
            <Card title="Annualized rolling volatility" meta={"Window " + data.parameters.volatility_window}>
              <IndicatorChart bars={bars} field="rolling_volatility" color="#ff8d75" title="Rolling volatility" />
            </Card>
          </div>
          <Card title="Signal counts" meta="Educational rule output">
            <div className="signal-counts">{Object.entries(data.signal_summary).map(([key, value]) =>
              <Metric key={key} label={key.toUpperCase()} value={number(value, 0)} />)}</div>
          </Card>
          <Card title="Indicator detail" meta={data.parameters.warmup_policy}>
            <div className="table-wrap"><table><thead><tr><th>Date</th><th>Close</th><th>Return</th><th>SMA fast</th><th>SMA slow</th><th>EMA</th><th>RSI</th><th>MACD hist.</th><th>Signal</th></tr></thead>
              <tbody>{bars.slice(-16).reverse().map((bar) => (
                <tr key={bar.timestamp}><td>{bar.timestamp}</td><td>{money(bar.close)}</td><td>{pct(bar.bar_return)}</td>
                  <td>{number(bar.sma_fast)}</td><td>{number(bar.sma_slow)}</td><td>{number(bar.ema)}</td>
                  <td>{number(bar.rsi)}</td><td>{number(bar.macd_histogram, 4)}</td><td><span className={"tag tag-" + bar.signal.toLowerCase()}>{bar.signal}</span></td></tr>
              ))}</tbody></table></div>
          </Card>
        </>
      ) : !error && !busy ? <Feedback>Load data to calculate indicators.</Feedback> : null}
    </div>
  );
}
