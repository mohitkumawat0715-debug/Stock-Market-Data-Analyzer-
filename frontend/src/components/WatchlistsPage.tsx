"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, post, remove } from "@/lib/api";
import { dateLabel } from "@/lib/format";
import type { Watchlist } from "@/lib/types";
import { Button, Card, Feedback, PageTitle, TextField } from "@/components/Frame";

export function WatchlistsPage() {
  const [lists, setLists] = useState<Watchlist[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [ticker, setTicker] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const result = await api<Watchlist[]>("/watchlists");
      setLists(result);
      setSelected((current) => current && result.some((list) => list.id === current) ? current : result[0]?.id || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Watchlists could not be loaded.");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function createList(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError(""); setMessage("");
    try {
      const created = await post<Watchlist>("/watchlists", { name });
      setName(""); setMessage("Watchlist created."); await load(); setSelected(created.id);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not create the watchlist."); }
    finally { setBusy(false); }
  }

  async function addTicker(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await post<Watchlist>("/watchlists/" + selected + "/items", { ticker, note: note || null });
      setTicker(""); setNote(""); setMessage("Ticker added."); await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not add ticker."); }
    finally { setBusy(false); }
  }

  async function deleteList(id: number) {
    if (!window.confirm("Delete this watchlist and its items?")) return;
    try { await remove("/watchlists/" + id); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not delete watchlist."); }
  }

  async function removeTicker(symbol: string) {
    if (!selected) return;
    try { await api<Watchlist>("/watchlists/" + selected + "/items/" + encodeURIComponent(symbol), { method: "DELETE" }); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not remove ticker."); }
  }

  const current = lists.find((list) => list.id === selected);
  return (
    <div className="page-stack">
      <PageTitle eyebrow="SAVED RESEARCH / 04" title="Keep a closer watch." description="Create local watchlists and track symbols across your analysis workspace." />
      {error ? <Feedback kind="error">{error}</Feedback> : null}
      {message ? <Feedback kind="success">{message}</Feedback> : null}
      <div className="content-grid">
        <Card title="Your lists" meta={lists.length + " saved"}>
          <div className="list-stack">
            {lists.length ? lists.map((list) => (
              <div className={"list-row " + (list.id === selected ? "list-row-active" : "")} key={list.id}>
                <button className="list-select" type="button" onClick={() => setSelected(list.id)}>
                  <strong>{list.name}</strong><span>{list.items.length} symbols · {dateLabel(list.created_at)}</span>
                </button>
                <button className="icon-button danger-text" type="button" aria-label={"Delete " + list.name} onClick={() => void deleteList(list.id)}>×</button>
              </div>
            )) : <div className="empty-state">No watchlists yet. Create one to save symbols.</div>}
          </div>
          <form className="stack-form" onSubmit={createList}>
            <TextField label="New watchlist" value={name} onChange={setName} placeholder="Long-term research" required />
            <Button type="submit" disabled={busy || !name.trim()}>Create list</Button>
          </form>
        </Card>
        <Card title={current?.name || "Select a watchlist"} meta={current ? "Persistent on this computer" : "Create a list to begin"}>
          {current ? <>
            <form className="inline-form" onSubmit={addTicker}>
              <TextField label="Ticker" value={ticker} onChange={setTicker} placeholder="MSFT" required />
              <TextField label="Note (optional)" value={note} onChange={setNote} placeholder="Earnings next week" />
              <Button type="submit" disabled={busy}>Add symbol</Button>
            </form>
            <div className="table-wrap"><table><thead><tr><th>Symbol</th><th>Note</th><th>Added</th><th></th></tr></thead>
              <tbody>{current.items.map((item) => <tr key={item.ticker}><td className="ticker-cell">{item.ticker}</td>
                <td>{item.note || "—"}</td><td>{dateLabel(item.added_at)}</td>
                <td><button className="text-button danger-text" type="button" onClick={() => void removeTicker(item.ticker)}>Remove</button></td></tr>)}</tbody>
            </table></div>
            {!current.items.length ? <div className="empty-state">Add a ticker to this list.</div> : null}
          </> : <div className="empty-state">Choose or create a watchlist to manage its symbols.</div>}
        </Card>
      </div>
      <Feedback>Watchlists are saved in the local SQLite database. This app does not provide account sync.</Feedback>
    </div>
  );
}
