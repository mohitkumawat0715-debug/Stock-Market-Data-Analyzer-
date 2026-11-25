export type Interval = "1d" | "1wk" | "1mo";
export type Source = "csv" | "yahoo";

export interface Bar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Metadata {
  ticker: string;
  interval: Interval;
  source: string;
  is_realtime: boolean;
  last_available_timestamp: string;
  bar_count: number;
  freshness_note: string;
}

export interface MarketData {
  metadata: Metadata;
  disclaimer: string;
  bars: Bar[];
}

export interface IndicatorBar extends Bar {
  bar_return: number | null;
  sma_fast: number | null;
  sma_slow: number | null;
  ema: number | null;
  rsi: number | null;
  macd_line: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  rolling_volatility: number | null;
  signal: "WARMUP" | "BUY" | "SELL" | "NEUTRAL";
  regime: "WARMUP" | "BULLISH" | "BEARISH" | "NEUTRAL";
}

export interface Indicators {
  metadata: Metadata;
  parameters: {
    interval: Interval;
    periods_per_year: number;
    sma_fast_window: number;
    sma_slow_window: number;
    ema_window: number;
    rsi_window: number;
    macd_fast_window: number;
    macd_slow_window: number;
    macd_signal_window: number;
    volatility_window: number;
    warmup_policy: string;
  };
  signal_summary: Record<string, number>;
  disclaimer: string;
  bars: IndicatorBar[];
}

export interface EquityPoint {
  timestamp: string;
  close: number;
  signal: string;
  desired_position: number;
  executed_position: number;
  earning_position: number;
  strategy_net_return: number;
  equity: number;
  drawdown: number;
}

export interface Backtest {
  metadata: Metadata;
  assumptions: {
    strategy_name: string;
    interval: Interval;
    periods_per_year: number;
    sma_fast_window: number;
    sma_slow_window: number;
    initial_capital: number;
    execution_delay_bars: number;
    execution_fill_convention: "next_bar_close";
    transaction_cost_bps: number;
    risk_free_rate_annual: number;
    risk_free_rate_per_bar: number;
    methodology_note: string;
  };
  metrics: {
    initial_capital: number;
    final_equity: number;
    total_return: number;
    total_return_pct: number;
    benchmark_buy_and_hold_return: number;
    annualized_volatility: number;
    max_drawdown: number;
    sharpe_ratio: number;
    trade_count: number;
    completed_round_trips: number;
  };
  trades: Array<{
    execution_timestamp: string;
    signal_timestamp: string;
    action: "BUY_ENTRY" | "SELL_EXIT";
    reference_close: number;
    cost_bps_applied: number;
  }>;
  equity_curve: EquityPoint[];
  disclaimer: string;
}

export interface WatchlistItem {
  ticker: string;
  note: string | null;
  added_at: string;
}

export interface Watchlist {
  id: number;
  name: string;
  created_at: string;
  items: WatchlistItem[];
}

export interface Portfolio {
  id: number;
  name: string;
  starting_cash: number;
  created_at: string;
}

export interface Holding {
  ticker: string;
  quantity: number;
  average_cost: number;
  cost_basis: number;
  market_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  price_source: string | null;
  price_as_of: string | null;
  price_is_realtime: boolean;
}

export interface PortfolioSummary {
  portfolio: Portfolio;
  cash: number;
  holdings_market_value: number;
  total_value: number | null;
  total_pnl: number | null;
  total_pnl_pct: number | null;
  realized_pnl: number;
  unrealized_pnl: number;
  total_fees: number;
  valuation_complete: boolean;
  holdings: Holding[];
  note: string;
}

export interface Transaction {
  id: number;
  ticker: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  fee: number;
  executed_at: string;
  price_source: string;
  note: string | null;
}

export type AlertKind =
  | "price_above"
  | "price_below"
  | "rsi_above"
  | "rsi_below"
  | "sma_crossover_buy"
  | "sma_crossover_sell";

export interface AlertRule {
  id: number;
  ticker: string;
  kind: AlertKind;
  threshold: number | null;
  cooldown_minutes: number;
  data_source: Source;
  active: boolean;
  condition_met: boolean;
  last_triggered_at: string | null;
  created_at: string;
}

export interface AlertEvent {
  id: number;
  rule_id: number;
  ticker: string;
  kind: AlertKind;
  triggered_at: string;
  observed_value: number | null;
  observed_signal: string | null;
  observation_source: string;
  observation_as_of: string | null;
  message: string;
  acknowledged: boolean;
}

export interface PollStatus {
  provider_configured: boolean;
  polling_enabled: boolean;
  polling_active: boolean;
  provider: string | null;
  poll_interval_seconds: number;
  max_symbols_per_cycle: number;
  last_fetched: string[];
  last_failed: Record<string, string>;
  last_skipped_over_cap: string[];
  last_finished_at: string | null;
  consecutive_failures: number;
  note: string;
}

export interface ApiProblem {
  error_code?: string;
  message?: string;
  details?: Record<string, unknown>;
}
