"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, post } from "@/lib/api";
import { dateLabel, money, number, pct } from "@/lib/format";
import type { Portfolio, PortfolioSummary, Transaction } from "@/lib/types";
import { Button, Card, Feedback, Metric, PageTitle, SelectField, TextField } from "@/components/Frame";

export function PortfolioPage() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [name, setName] = useState("");
  const [startingCash, setStartingCash] = useState("10000");
  const [ticker, setTicker] = useState("AAPL");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [quantity, setQuantity] = useState("1");
  const [price, setPrice] = useState("");
  const [fee, setFee] = useState("0");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const result = await api<Portfolio[]>("/portfolios");
      setPortfolios(result);
      setSelected((current) => current && result.some((portfolio) => portfolio.id === current) ? current : result[0]?.id || null);
    } catch (err) { setError(err instanceof Error ? err.message : "Portfolios could not be loaded."); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const loadSelected = useCallback(async (id: number) => {
    try {
      const [state, tx] = await Promise.all([
        api<PortfolioSummary>("/portfolios/" + id),
        api<Transaction[]>("/portfolios/" + id + "/transactions"),
      ]);
      setSummary(state); setTransactions(tx);
    } catch (err) { setError(err instanceof Error ? err.message : "Portfolio details could not be loaded."); }
  }, []);
  useEffect(() => { if (selected) void loadSelected(selected); else { setSummary(null); setTransactions([]); } }, [selected, loadSelected]);

  async function createPortfolio(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const created = await post<Portfolio>("/portfolios", { name, starting_cash: Number(startingCash) });
      setName(""); setMessage("Paper portfolio created."); await load(); setSelected(created.id);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not create portfolio."); }
    finally { setBusy(false); }
  }

  async function addTransaction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await post<Transaction>("/portfolios/" + selected + "/transactions", {
        ticker, side, quantity: Number(quantity), price: price ? Number(price) : null, fee: Number(fee),
      });
      setMessage(side + " transaction recorded."); setPrice("");
      await loadSelected(selected);
    } catch (err) { setError(err instanceof Error ? err.message : "Transaction was rejected."); }
    finally { setBusy(false); }
  }

  return (
    <div className="page-stack">
      <PageTitle eyebrow="PAPER PORTFOLIO / 05" title="Practice the ledger." description="Record simulated transactions and review cash, holdings, fees, and estimated P&L." />
      <Feedback>Paper trading only. No orders are sent to a broker. Values use the most recent local CSV close or optional stored quote.</Feedback>
      {error ? <Feedback kind="error">{error}</Feedback> : null}
      {message ? <Feedback kind="success">{message}</Feedback> : null}
      <div className="content-grid">
        <Card title="Choose portfolio" meta={portfolios.length + " saved"}>
          <SelectField label="Portfolio" value={selected ? String(selected) : ""} onChange={(value) => setSelected(value ? Number(value) : null)}
            options={[["", "Select a portfolio"], ...portfolios.map((item) => [String(item.id), item.name] as [string, string])]} />
          <form className="stack-form" onSubmit={createPortfolio}>
            <TextField label="New portfolio" value={name} onChange={setName} placeholder="Learning account" required />
            <TextField label="Starting cash" type="number" min={1} step={100} value={startingCash} onChange={setStartingCash} required />
            <Button type="submit" disabled={busy}>Create paper portfolio</Button>
          </form>
        </Card>
        <Card title="Record a paper transaction" meta={selected ? "Portfolio #" + selected : "Create a portfolio first"}>
          <form className="form-grid" onSubmit={addTransaction}>
            <TextField label="Ticker" value={ticker} onChange={setTicker} required />
            <SelectField label="Side" value={side} onChange={(value) => setSide(value as "BUY" | "SELL")} options={[["BUY", "Buy"], ["SELL", "Sell"]]} />
            <TextField label="Quantity" type="number" min={0.000001} step={0.01} value={quantity} onChange={setQuantity} required />
            <TextField label="Fill price (blank = local price)" type="number" min={0.000001} step={0.01} value={price} onChange={setPrice} />
            <TextField label="Fee" type="number" min={0} step={0.01} value={fee} onChange={setFee} required />
            <Button type="submit" disabled={busy || !selected}>Record transaction</Button>
          </form>
        </Card>
      </div>
      {summary ? <>
        <div className="metric-grid">
          <Metric label="TOTAL VALUE" value={money(summary.total_value)} sub={summary.valuation_complete ? "Valuation complete" : "Some holdings lack a price"} />
          <Metric label="CASH" value={money(summary.cash)} />
          <Metric label="REALIZED P&L" value={money(summary.realized_pnl)} tone={summary.realized_pnl >= 0 ? "positive" : "negative"} />
          <Metric label="UNREALIZED P&L" value={money(summary.unrealized_pnl)} tone={summary.unrealized_pnl >= 0 ? "positive" : "negative"} />
        </div>
        <Card title={summary.portfolio.name + " holdings"} meta={"Total P&L " + money(summary.total_pnl) + " · " + pct(summary.total_pnl_pct ? summary.total_pnl_pct / 100 : null)}>
          <div className="table-wrap"><table><thead><tr><th>Symbol</th><th>Shares</th><th>Avg. cost</th><th>Latest price</th><th>Market value</th><th>Unrealized P&L</th><th>Price source</th></tr></thead>
            <tbody>{summary.holdings.map((holding) => <tr key={holding.ticker}>
              <td className="ticker-cell">{holding.ticker}</td><td>{number(holding.quantity, 4)}</td><td>{money(holding.average_cost)}</td>
              <td>{money(holding.market_price)}</td><td>{money(holding.market_value)}</td>
              <td className={holding.unrealized_pnl === null ? "" : holding.unrealized_pnl >= 0 ? "positive-text" : "negative-text"}>{money(holding.unrealized_pnl)}</td>
              <td>{holding.price_source || "Unavailable"}</td></tr>)}</tbody></table></div>
          {!summary.holdings.length ? <div className="empty-state">No open positions yet.</div> : null}
        </Card>
        <Card title="Transaction history" meta={transactions.length + " records"}>
          {transactions.length ? <div className="table-wrap"><table><thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Quantity</th><th>Price</th><th>Fee</th><th>Source</th></tr></thead>
            <tbody>{transactions.slice().reverse().map((tx) => <tr key={tx.id}><td>{dateLabel(tx.executed_at)}</td><td className="ticker-cell">{tx.ticker}</td>
              <td>{tx.side}</td><td>{number(tx.quantity, 4)}</td><td>{money(tx.price)}</td><td>{money(tx.fee)}</td><td>{tx.price_source}</td></tr>)}</tbody></table></div>
            : <div className="empty-state">Paper transactions will appear here.</div>}
        </Card>
        <p className="method-note">{summary.note}</p>
      </> : null}
    </div>
  );
}
