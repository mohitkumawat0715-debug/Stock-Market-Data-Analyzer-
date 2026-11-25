"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  ["/", "Overview"],
  ["/ticker/AAPL", "Analysis"],
  ["/backtest", "Backtest"],
  ["/watchlists", "Watchlists"],
  ["/portfolio", "Portfolio"],
  ["/alerts", "Alerts"],
];

export function PrimaryNavigation() {
  const pathname = usePathname();

  function isActive(href: string) {
    if (href === "/") return pathname === "/";
    if (href === "/ticker/AAPL") return pathname.startsWith("/ticker/");
    return pathname === href || pathname.startsWith(href + "/");
  }

  return (
    <nav className="nav-links" aria-label="Primary navigation">
      {links.map(([href, label]) => {
        const active = isActive(href);
        return (
          <Link
            href={href}
            key={href}
            className={active ? "nav-link nav-link-active" : "nav-link"}
            aria-current={active ? "page" : undefined}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
