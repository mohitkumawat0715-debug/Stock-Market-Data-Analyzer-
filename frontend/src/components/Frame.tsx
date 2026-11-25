import Link from "next/link";

const links = [
  ["/", "Overview"],
  ["/ticker/AAPL", "Analysis"],
  ["/backtest", "Backtest"],
  ["/watchlists", "Watchlists"],
  ["/portfolio", "Portfolio"],
  ["/alerts", "Alerts"],
];

export function Frame({ children }: { children: React.ReactNode }) {
  return (
    <>
      <header className="topbar">
        <Link className="brand" href="/">
          <span className="brand-mark">S</span>
          <span>MARKET<span className="brand-light">/LAB</span></span>
        </Link>
        <nav className="nav-links" aria-label="Primary navigation">
          {links.map(([href, label]) => (
            <Link href={href} key={href}>{label}</Link>
          ))}
        </nav>
        <span className="local-pill"><span className="status-dot" /> LOCAL WORKSPACE</span>
      </header>
      <main className="site-main">{children}</main>
      <footer className="site-footer">
        <span>Market/Lab · Educational analysis only</span>
        <span>Historical data may be delayed. Not financial advice.</span>
      </footer>
    </>
  );
}

export function Disclaimer() {
  return (
    <div className="disclaimer">
      <span className="disclaimer-icon">i</span>
      <p><strong>For education only.</strong> Indicators, signals, quotes, and simulations are not financial advice or trade recommendations.</p>
    </div>
  );
}

export function PageTitle({ eyebrow, title, description, action }: {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-title">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action ? <div className="title-action">{action}</div> : null}
    </div>
  );
}

export function Card({ title, meta, children, className = "" }: {
  title?: string;
  meta?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={"card " + className}>
      {title ? <div className="card-heading"><h2>{title}</h2>{meta ? <span>{meta}</span> : null}</div> : null}
      {children}
    </section>
  );
}

export function Metric({ label, value, sub, tone = "" }: {
  label: string;
  value: string;
  sub?: string;
  tone?: string;
}) {
  return (
    <div className={"metric " + tone}>
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
      {sub ? <small>{sub}</small> : null}
    </div>
  );
}

export function Feedback({ kind = "info", children }: {
  kind?: "info" | "error" | "success";
  children: React.ReactNode;
}) {
  return <div className={"feedback feedback-" + kind} role={kind === "error" ? "alert" : "status"}>{children}</div>;
}

export function Button({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...props} className={"button " + (props.className || "")}>{children}</button>;
}

export function SelectField({ label, value, onChange, options }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<[string, string]>;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map(([option, text]) => <option key={option} value={option}>{text}</option>)}
      </select>
    </label>
  );
}

export function TextField({ label, value, onChange, type = "text", min, step, placeholder, required = false }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  min?: number;
  step?: number;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input type={type} value={value} onChange={(event) => onChange(event.target.value)}
        min={min} step={step} placeholder={placeholder} required={required} />
    </label>
  );
}
