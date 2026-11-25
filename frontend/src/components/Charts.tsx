import type { Bar, EquityPoint, IndicatorBar } from "@/lib/types";

export function PriceChart({ bars, overlays = [] }: {
  bars: Bar[];
  overlays?: Array<{ label: string; color: string; values: Array<number | null> }>;
}) {
  if (!bars.length) return <div className="chart-empty">No bars in this date range.</div>;
  const width = 1000;
  const height = 320;
  const left = 44;
  const right = 14;
  const top = 16;
  const chartHeight = 220;
  const values = bars.flatMap((bar) => [bar.high, bar.low]);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const spread = Math.max(maxValue - minValue, Math.abs(maxValue) * 0.015, 1);
  const min = minValue - spread * 0.08;
  const max = maxValue + spread * 0.08;
  const y = (value: number) => top + ((max - value) / (max - min)) * chartHeight;
  const plotWidth = width - left - right;
  const step = plotWidth / bars.length;
  const candleWidth = Math.max(2, Math.min(13, step * 0.56));
  const maxVolume = Math.max(...bars.map((bar) => bar.volume), 1);
  const volumeY = top + chartHeight + 16;
  return (
    <div className="chart-wrap">
      <svg className="chart-svg" viewBox={"0 0 " + width + " " + height} role="img" aria-label="Candlestick and volume chart">
        {[0, 1, 2, 3].map((tick) => {
          const value = max - ((max - min) * tick) / 3;
          const yy = y(value);
          return <g key={tick}><line x1={left} x2={width - right} y1={yy} y2={yy} className="grid-line" />
            <text x={left - 8} y={yy + 4} textAnchor="end" className="axis-label">{value.toFixed(2)}</text></g>;
        })}
        {bars.map((bar, index) => {
          const x = left + index * step + step / 2;
          const up = bar.close >= bar.open;
          const candleTop = Math.min(y(bar.open), y(bar.close));
          const candleHeight = Math.max(1.5, Math.abs(y(bar.open) - y(bar.close)));
          const vHeight = (bar.volume / maxVolume) * 47;
          return <g key={bar.timestamp}>
            <line x1={x} x2={x} y1={y(bar.high)} y2={y(bar.low)} className={up ? "wick-up" : "wick-down"} />
            <rect x={x - candleWidth / 2} y={candleTop} width={candleWidth} height={candleHeight}
              className={up ? "candle-up" : "candle-down"} rx="1" />
            <rect x={x - candleWidth / 2} y={volumeY + 49 - vHeight} width={candleWidth}
              height={vHeight} className={up ? "volume-up" : "volume-down"} />
          </g>;
        })}
        {overlays.map((overlay) => {
          const points = overlay.values.map((value, index) => {
            if (value === null || !Number.isFinite(value)) return null;
            const x = left + index * step + step / 2;
            return [x, y(value)] as const;
          });
          let drawing = false;
          const path = points.map((point) => {
            if (!point) {
              drawing = false;
              return "";
            }
            const command = drawing ? "L " : "M ";
            drawing = true;
            return command + point[0].toFixed(1) + " " + point[1].toFixed(1);
          }).filter(Boolean).join(" ");
          return path ? <path key={overlay.label} d={path} fill="none" stroke={overlay.color}
            strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" /> : null;
        })}
        <line x1={left} x2={width - right} y1={volumeY + 50} y2={volumeY + 50} className="grid-line" />
        <text x={left} y={height - 6} className="axis-label">{bars[0].timestamp}</text>
        <text x={width - right} y={height - 6} textAnchor="end" className="axis-label">{bars[bars.length - 1].timestamp}</text>
        <text x={left} y={volumeY + 66} className="axis-label">VOLUME</text>
      </svg>
    </div>
  );
}

export function IndicatorChart({ bars, field, color, title }: {
  bars: IndicatorBar[];
  field: "rsi" | "macd_line" | "macd_signal" | "macd_histogram" | "rolling_volatility";
  color: string;
  title: string;
}) {
  const values = bars.map((bar) => bar[field]);
  return <LineChart values={values} color={color} title={title} />;
}

export function LineChart({ values, color = "#58d6a1", title = "Series" }: {
  values: Array<number | null>;
  color?: string;
  title?: string;
}) {
  const valid = values.filter((value): value is number => value !== null && Number.isFinite(value));
  if (!valid.length) return <div className="chart-empty">Waiting for full indicator lookback.</div>;
  const width = 800;
  const height = 150;
  const padding = 12;
  const low = Math.min(...valid);
  const high = Math.max(...valid);
  const range = Math.max(high - low, Math.abs(high) * 0.02, 0.01);
  const points = values.map((value, index) => {
    if (value === null || !Number.isFinite(value)) return null;
    const x = padding + (index / Math.max(values.length - 1, 1)) * (width - padding * 2);
    const y = height - padding - ((value - low) / range) * (height - padding * 2);
    return [x, y] as const;
  }).filter((point): point is readonly [number, number] => point !== null);
  const path = points.map((point, index) => (index === 0 ? "M " : "L ") + point[0].toFixed(1) + " " + point[1].toFixed(1)).join(" ");
  return (
    <div className="line-chart-wrap">
      <svg viewBox={"0 0 " + width + " " + height} className="line-chart" role="img" aria-label={title}>
        <line x1="0" x2={width} y1={height / 2} y2={height / 2} className="grid-line" />
        <path d={path} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
      <div className="chart-range"><span>{low.toFixed(2)}</span><span>{high.toFixed(2)}</span></div>
    </div>
  );
}

export function EquityChart({ points, field, color, label }: {
  points: EquityPoint[];
  field: "equity" | "drawdown";
  color: string;
  label: string;
}) {
  return <LineChart values={points.map((point) => point[field])} color={color} title={label} />;
}
