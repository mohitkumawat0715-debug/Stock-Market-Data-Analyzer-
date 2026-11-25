"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, query } from "@/lib/api";
import { dateLabel, money, number, pct } from "@/lib/format";
import type { Bar, Interval, MarketData, Source } from "@/lib/types";
import { Card, Feedback, Metric, PageTitle, SelectField, TextField, Button } from "@/components/Frame";
import { PriceChart } from "@/components/Charts";

interface Health {
  available_csv_tickers: string[];
  status: string;
}

export function MarketOverview() {
  const [ticker, setTicker] = useState("AAPL");
  const [source, setSource] = useState<Source>("csv");
  const [interval, setInterval] = useState<Interval>("1d");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [data, setData] = useState<MarketData | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const apiAvailable = health?.status === "ok";

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const path = "/market-data/" + encodeURIComponent(ticker.trim().toUpperCase()) +
        query({ source, interval, start_date: startDate, end_date: endDate });
      setData(await api<MarketData>(path));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Market data could not be loaded.");
    } finally {
      setBusy(false);
    }
  }, [ticker, source, interval, startDate, endDate]);

  useEffect(() => {
    api<Health>("/health")
      .then(setHealth)
      .catch(() => setHealth({ status: "unavailable", available_csv_tickers: [] }));
    void load();
  }, [load]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void load();
  }

  const bars = data?.bars || [];
  const last = bars[bars.length - 1];
  const prev = bars.length > 1 ? bars[bars.length - 2] : undefined;
  const move = last && prev && prev.close !== 0 ? last.close / prev.close - 1 : null;

  return (
    <div className="page-stack">
      <PageTitle eyebrow="MARKET OVERVIEW / 01" title="Read the tape." description="Explore historical OHLCV data and understand what changed, when, and by how much."
        action={
          <span className={"live-label " + (health ? apiAvailable ? "live-label-ready" : "live-label-offline" : "")}>
            <span className={"status-dot " + (health ? apiAvailable ? "status-dot-ready" : "status-dot-offline" : "")} />
            {health ? apiAvailable ? "API CONNECTED" : "API UNAVAILABLE" : "CONNECTING TO API"}
          </span>
        } />
      <Card className="filter-card">
        <form className="filter-grid" onSubmit={submit}>
          <TextField label="Ticker" value={ticker} onChange={setTicker} placeholder="AAPL" required />
          <SelectField label="Data source" value={source} onChange={(value) => setSource(value as Source)}
            options={[["csv", "Offline sample CSV"], ["yahoo", "Yahoo Finance history"]]} />
          <SelectField label="Interval" value={interval} onChange={(value) => setInterval(value as Interval)}
            options={[["1d", "Daily"], ["1wk", "Weekly"], ["1mo", "Monthly"]]} />
          <TextField label="From" type="date" value={startDate} onChange={setStartDate} />
          <TextField label="To" type="date" value={endDate} onChange={setEndDate} />
          <Button type="submit" disabled={busy}>{busy ? "Loading…" : "Load market data"}</Button>
        </form>
        {source === "csv" && health?.available_csv_tickers?.length ? (
          <div className="quick-tickers"><span>OFFLINE SYMBOLS</span>
            {health.available_csv_tickers.map((symbol) => (
              <button className="chip" key={symbol} type="button" onClick={() => setTicker(symbol)}>{symbol}</button>
            ))}
          </div>
        ) : null}
      </Card>
      {error ? <Feedback kind="error">{error}</Feedback> : null}
      {data ? (
        <>
          <div className="metric-grid">
            <Metric label="LAST CLOSE" value={money(last?.close)} sub={dateLabel(last?.timestamp)} />
            <Metric label="BAR RETURN" value={pct(move)} tone={move === null ? "" : move >= 0 ? "positive" : "negative"}
              sub={prev ? "Compared with prior " + interval + " bar" : "Waiting for prior bar"} />
            <Metric label="LATEST VOLUME" value={number(last?.volume, 0)} sub={data.metadata.bar_count + " bars loaded"} />
            <Metric label="SOURCE" value={data.metadata.source === "local_csv" ? "Local CSV" : "Yahoo history"}
              sub={"Latest bar " + dateLabel(data.metadata.last_available_timestamp)} />
          </div>
          <div className="content-grid">
            <Card title={data.metadata.ticker + " · price and volume"} meta={interval.toUpperCase() + " bars"}>
              <PriceChart bars={bars} />
            </Card>
            <Card title="Data provenance" meta="Freshness">
              <div className="freshness-card">
                <div className="freshness-state"><span className="status-dot" /> HISTORICAL DATA</div>
                <p>{data.metadata.freshness_note}</p>
                <dl>
                  <div><dt>Source</dt><dd>{data.metadata.source}</dd></div>
                  <div><dt>Realtime</dt><dd>No</dd></div>
                  <div><dt>Interval</dt><dd>{data.metadata.interval}</dd></div>
                  <div><dt>Last available</dt><dd>{dateLabel(data.metadata.last_available_timestamp)}</dd></div>
                </dl>
              </div>
            </Card>
          </div>
          <Card title="Recent bars" meta="Newest first">
            <div className="table-wrap"><table><thead><tr><th>Date</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th></tr></thead>
              <tbody>{bars.slice(-12).reverse().map((bar: Bar) => (
                <tr key={bar.timestamp}><td>{bar.timestamp}</td><td>{money(bar.open)}</td><td>{money(bar.high)}</td>
                  <td>{money(bar.low)}</td><td>{money(bar.close)}</td><td>{number(bar.volume, 0)}</td></tr>
              ))}</tbody></table></div>
          </Card>
          <div className="next-links">
            <Link className="next-link" href={"/ticker/" + encodeURIComponent(data.metadata.ticker)}>Open technical analysis <span>↗</span></Link>
            <Link className="next-link" href={"/backtest?ticker=" + encodeURIComponent(data.metadata.ticker)}>Explore a strategy simulation <span>↗</span></Link>
          </div>
        </>
      ) : !error && !busy ? <Feedback>Choose a ticker and load data to begin.</Feedback> : null}
    </div>
  );
}
