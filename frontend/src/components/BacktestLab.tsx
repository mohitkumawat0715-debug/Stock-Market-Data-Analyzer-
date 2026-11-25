"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, query } from "@/lib/api";
import { dateLabel, money, number, pct } from "@/lib/format";
import type { Backtest, Interval, Source } from "@/lib/types";
import { Card, Feedback, Metric, PageTitle, SelectField, TextField, Button } from "@/components/Frame";
import { EquityChart } from "@/components/Charts";

interface BacktestQuery {
  ticker: string;
  source: Source;
  interval: Interval;
  start: string;
  end: string;
  fast: string;
  slow: string;
  capital: string;
  fee: string;
  riskFree: string;
}

function requestBacktest(input: BacktestQuery): Promise<Backtest> {
  const path = "/backtest/" + encodeURIComponent(input.ticker.trim().toUpperCase()) +
    query({
      source: input.source,
      interval: input.interval,
      start_date: input.start,
      end_date: input.end,
      sma_fast: input.fast,
      sma_slow: input.slow,
      initial_capital: input.capital,
      transaction_cost_bps: input.fee,
      risk_free_rate: String(Number(input.riskFree) / 100),
    });
  return api<Backtest>(path);
}

export function BacktestLab() {
  const [ticker, setTicker] = useState("AAPL");
  const [source, setSource] = useState<Source>("csv");
  const [interval, setInterval] = useState<Interval>("1d");
  const [fast, setFast] = useState("10");
  const [slow, setSlow] = useState("30");
  const [capital, setCapital] = useState("10000");
  const [fee, setFee] = useState("10");
  const [riskFree, setRiskFree] = useState("2");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [data, setData] = useState<Backtest | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    setBusy(true);
    setError("");
    try {
      setData(await requestBacktest({ ticker, source, interval, start, end, fast, slow, capital, fee, riskFree }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backtest could not be completed.");
    } finally {
      setBusy(false);
    }
  }, [ticker, source, interval, start, end, fast, slow, capital, fee, riskFree]);

  useEffect(() => {
    const requestedTicker = new URLSearchParams(window.location.search).get("ticker");
    const initialTicker = requestedTicker ? requestedTicker.toUpperCase() : "AAPL";
    if (requestedTicker) setTicker(initialTicker);
    setBusy(true);
    requestBacktest({
      ticker: initialTicker, source: "csv", interval: "1d", start: "", end: "",
      fast: "10", slow: "30", capital: "10000", fee: "10", riskFree: "2",
    }).then(setData).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Backtest could not be completed.");
    }).finally(() => setBusy(false));
  }, []);
  const metrics = data?.metrics;

  return (
    <div className="page-stack">
      <PageTitle eyebrow="STRATEGY LAB / 03" title="Test the rules." description="Run a long-only SMA crossover simulation with explicit execution delay and configurable fees." />
      <Card className="filter-card">
        <form className="filter-grid backtest-filters" onSubmit={run}>
          <TextField label="Ticker" value={ticker} onChange={setTicker} required />
          <SelectField label="Source" value={source} onChange={(value) => setSource(value as Source)} options={[["csv", "Offline CSV"], ["yahoo", "Yahoo history"]]} />
          <SelectField label="Interval" value={interval} onChange={(value) => setInterval(value as Interval)} options={[["1d", "Daily"], ["1wk", "Weekly"], ["1mo", "Monthly"]]} />
          <TextField label="Fast SMA" type="number" min={2} value={fast} onChange={setFast} required />
          <TextField label="Slow SMA" type="number" min={3} value={slow} onChange={setSlow} required />
          <TextField label="Starting cash" type="number" min={1} step={100} value={capital} onChange={setCapital} required />
          <TextField label="Fee (basis points)" type="number" min={0} step={1} value={fee} onChange={setFee} required />
          <TextField label="Risk-free rate (%)" type="number" min={-10} step={0.1} value={riskFree} onChange={setRiskFree} required />
          <TextField label="From" type="date" value={start} onChange={setStart} />
          <TextField label="To" type="date" value={end} onChange={setEnd} />
          <Button type="submit" disabled={busy}>{busy ? "Running…" : "Run backtest"}</Button>
        </form>
      </Card>
      {error ? <Feedback kind="error">{error}</Feedback> : null}
      {data && metrics ? (
        <>
          <div className="metric-grid metric-grid-six">
            <Metric label="FINAL EQUITY" value={money(metrics.final_equity)} sub={"Start " + money(metrics.initial_capital)} />
            <Metric label="TOTAL RETURN" value={pct(metrics.total_return)} tone={metrics.total_return >= 0 ? "positive" : "negative"} />
            <Metric label="BUY & HOLD" value={pct(metrics.benchmark_buy_and_hold_return)} />
            <Metric label="MAX DRAWDOWN" value={pct(metrics.max_drawdown)} tone="negative" />
            <Metric label="ANNUAL VOLATILITY" value={pct(metrics.annualized_volatility)} />
            <Metric label="SHARPE" value={number(metrics.sharpe_ratio)} sub={metrics.trade_count + " fills"} />
          </div>
          <div className="content-grid">
            <Card title="Equity curve" meta="Net of estimated transaction costs"><EquityChart points={data.equity_curve} field="equity" color="#55d69f" label="Equity curve" /></Card>
            <Card title="Drawdown" meta="Peak-to-trough"><EquityChart points={data.equity_curve} field="drawdown" color="#ff806f" label="Drawdown" /></Card>
          </div>
          <Card title="Simulation assumptions" meta="Read before interpreting results">
            <div className="assumption-grid">
              <div><span>Fill convention</span><strong>Next bar close</strong></div>
              <div><span>Delay</span><strong>{data.assumptions.execution_delay_bars} bar</strong></div>
              <div><span>Bar frequency</span><strong>{data.assumptions.interval} · {data.assumptions.periods_per_year}/year</strong></div>
              <div><span>Cost per fill</span><strong>{number(data.assumptions.transaction_cost_bps)} bps</strong></div>
              <div><span>Annual risk-free</span><strong>{pct(data.assumptions.risk_free_rate_annual)}</strong></div>
              <div><span>Per-bar risk-free</span><strong>{pct(data.assumptions.risk_free_rate_per_bar, 4)}</strong></div>
            </div>
            <p className="method-note">{data.assumptions.methodology_note}</p>
          </Card>
          <Card title="Executed orders" meta={metrics.trade_count + " position changes"}>
            {data.trades.length ? <div className="table-wrap"><table><thead><tr><th>Signal date</th><th>Fill date</th><th>Action</th><th>Reference close</th><th>Cost</th></tr></thead>
              <tbody>{data.trades.map((trade, index) => <tr key={trade.execution_timestamp + trade.action + index}>
                <td>{dateLabel(trade.signal_timestamp)}</td><td>{dateLabel(trade.execution_timestamp)}</td>
                <td><span className={"tag tag-" + (trade.action === "BUY_ENTRY" ? "buy" : "sell")}>{trade.action}</span></td>
                <td>{money(trade.reference_close)}</td><td>{number(trade.cost_bps_applied)} bps</td></tr>)}</tbody></table></div>
              : <div className="empty-state">No crossovers occurred in this date range.</div>}
          </Card>
        </>
      ) : !error && !busy ? <Feedback>Choose parameters and run a simulation.</Feedback> : null}
    </div>
  );
}
