"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, patch, post, query, remove } from "@/lib/api";
import { dateLabel, number } from "@/lib/format";
import type { AlertEvent, AlertKind, AlertRule, PollStatus, Source } from "@/lib/types";
import { Button, Card, Feedback, PageTitle, SelectField, TextField } from "@/components/Frame";

const ruleKinds: Array<[AlertKind, string]> = [
  ["price_above", "Price rises above"],
  ["price_below", "Price falls below"],
  ["rsi_above", "RSI rises above"],
  ["rsi_below", "RSI falls below"],
  ["sma_crossover_buy", "SMA crossover buy"],
  ["sma_crossover_sell", "SMA crossover sell"],
];

export function AlertsPage() {
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [status, setStatus] = useState<PollStatus | null>(null);
  const [ticker, setTicker] = useState("AAPL");
  const [kind, setKind] = useState<AlertKind>("price_above");
  const [threshold, setThreshold] = useState("");
  const [source, setSource] = useState<Source>("csv");
  const [cooldown, setCooldown] = useState("60");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const needsThreshold = kind === "price_above" || kind === "price_below" || kind === "rsi_above" || kind === "rsi_below";

  const load = useCallback(async () => {
    try {
      const [ruleData, eventData, pollStatus] = await Promise.all([
        api<AlertRule[]>("/alerts/rules"),
        api<AlertEvent[]>("/alerts/events" + query({ limit: 100 })),
        api<PollStatus>("/quotes/status"),
      ]);
      setRules(ruleData); setEvents(eventData); setStatus(pollStatus);
    } catch (err) { setError(err instanceof Error ? err.message : "Alert data could not be loaded."); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function createRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      await post<AlertRule>("/alerts/rules", {
        ticker, kind, threshold: needsThreshold ? Number(threshold) : null,
        data_source: source, cooldown_minutes: Number(cooldown),
      });
      setMessage("Alert rule created."); setThreshold(""); await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Rule could not be created."); }
    finally { setBusy(false); }
  }

  async function evaluate() {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await post<{ evaluated: number; triggered: number; errors: unknown[] }>("/alerts/evaluate", {});
      setMessage("Evaluated " + result.evaluated + " rules; " + result.triggered + " new events.");
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Evaluation failed."); }
    finally { setBusy(false); }
  }

  async function poll() {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await post<{ fetched: string[]; failed: Record<string, string>; skipped_over_cap: string[] }>("/quotes/poll", {});
      setMessage("Fetched " + result.fetched.length + " quote(s); " + Object.keys(result.failed).length + " failed.");
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Polling failed."); }
    finally { setBusy(false); }
  }

  async function toggleRule(rule: AlertRule) {
    try { await patch<AlertRule>("/alerts/rules/" + rule.id, { active: !rule.active }); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Rule update failed."); }
  }

  async function deleteRule(id: number) {
    try { await remove("/alerts/rules/" + id); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Rule delete failed."); }
  }

  async function acknowledge(id: number) {
    try { await post<AlertEvent>("/alerts/events/" + id + "/acknowledge", {}); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Event update failed."); }
  }

  return (
    <div className="page-stack">
      <PageTitle eyebrow="MONITORING / 06" title="Watch for a condition." description="Create educational price and indicator rules, then review the observations that triggered them." />
      {error ? <Feedback kind="error">{error}</Feedback> : null}
      {message ? <Feedback kind="success">{message}</Feedback> : null}
      <div className="content-grid">
        <Card title="Quote polling" meta={status?.provider || "Optional provider"}>
          <div className="poll-status">
            <span className={"status-badge " + (status?.provider_configured ? "status-ready" : "")}>
              {status?.provider_configured ? "PROVIDER CONFIGURED" : "OFFLINE MODE"}
            </span>
            <p>{status?.note || "Checking provider settings…"}</p>
            {status?.last_finished_at ? <p>Last cycle: {dateLabel(status.last_finished_at)} · {status.last_fetched.length} fetched · {Object.keys(status.last_failed).length} failed</p> : null}
            <Button type="button" onClick={() => void poll()} disabled={busy || !status?.provider_configured}>
              {status?.provider_configured ? "Poll quotes now" : "Add optional Finnhub key to enable"}
            </Button>
          </div>
        </Card>
        <Card title="Add an alert rule" meta="Persisted locally">
          <form className="form-grid" onSubmit={createRule}>
            <TextField label="Ticker" value={ticker} onChange={setTicker} required />
            <SelectField label="Condition" value={kind} onChange={(value) => setKind(value as AlertKind)} options={ruleKinds} />
            {needsThreshold ? <TextField label={kind.startsWith("rsi") ? "RSI threshold" : "Price threshold"} type="number" step={0.1} value={threshold} onChange={setThreshold} required /> : null}
            <SelectField label="Historical data source" value={source} onChange={(value) => setSource(value as Source)} options={[["csv", "Offline CSV"], ["yahoo", "Yahoo history"]]} />
            <TextField label="Cooldown (minutes)" type="number" min={0} value={cooldown} onChange={setCooldown} required />
            <Button type="submit" disabled={busy}>Create rule</Button>
          </form>
        </Card>
      </div>
      <Card title="Alert rules" meta={rules.length + " configured"}>
        {rules.length ? <div className="table-wrap"><table><thead><tr><th>Symbol</th><th>Condition</th><th>Source</th><th>Status</th><th>Cooldown</th><th>Actions</th></tr></thead>
          <tbody>{rules.map((rule) => <tr key={rule.id}><td className="ticker-cell">{rule.ticker}</td>
            <td>{ruleKinds.find(([value]) => value === rule.kind)?.[1]} {rule.threshold !== null ? number(rule.threshold) : ""}</td>
            <td>{rule.data_source}</td><td>{rule.active ? rule.condition_met ? "Condition met" : "Active" : "Paused"}</td>
            <td>{rule.cooldown_minutes} min</td><td className="actions-cell">
              <button className="text-button" type="button" onClick={() => void toggleRule(rule)}>{rule.active ? "Pause" : "Resume"}</button>
              <button className="text-button danger-text" type="button" onClick={() => void deleteRule(rule.id)}>Delete</button>
            </td></tr>)}</tbody></table></div>
          : <div className="empty-state">No rules yet. Create one above, then evaluate it.</div>}
        <div className="card-actions"><Button type="button" onClick={() => void evaluate()} disabled={busy}>Evaluate rules now</Button></div>
      </Card>
      <Card title="Alert events" meta={events.filter((event) => !event.acknowledged).length + " unacknowledged"}>
        {events.length ? <div className="event-list">{events.map((event) => <article className={"event-row " + (event.acknowledged ? "event-read" : "")} key={event.id}>
          <div className="event-marker" />
          <div className="event-body"><div className="event-title"><strong>{event.ticker}</strong><span>{event.kind.replaceAll("_", " ")}</span><time>{dateLabel(event.triggered_at)}</time></div>
            <p>{event.message}</p><small>Source: {event.observation_source} · As of {event.observation_as_of || "unknown"} · Value {number(event.observed_value)}</small></div>
          {!event.acknowledged ? <button className="text-button" type="button" onClick={() => void acknowledge(event.id)}>Acknowledge</button> : <span className="muted">Read</span>}
        </article>)}</div> : <div className="empty-state">Triggered events will appear here.</div>}
      </Card>
      <Feedback>Rules use historical bars or optional provider snapshots. Polling is disabled without credentials, and quotes are never labeled guaranteed real-time.</Feedback>
    </div>
  );
}
