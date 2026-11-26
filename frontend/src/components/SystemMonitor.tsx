import { useEffect, useId, useState } from "react";
import type { CSSProperties } from "react";
import { api } from "../api";

type Metrics = {
  sampled_at: number;
  cpu: { percent: number; logical_cores: number | null; physical_cores: number | null };
  memory: { percent: number; used_bytes: number; available_bytes: number; total_bytes: number };
  disk: { percent: number; used_bytes: number; free_bytes: number; total_bytes: number };
  host_uptime_seconds: number;
  api_memory_bytes: number;
  api_uptime_seconds: number;
};

function gigabytes(bytes: number) {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

function uptime(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  return `${Math.floor(hours / 24)}d ${hours % 24}h ${Math.floor(seconds / 60) % 60}m`;
}

function Trend({ values, label, color }: { values: number[]; label: string; color: string }) {
  const gradientId = useId();
  if (values.length < 2) {
    return (
      <div className="trend-wait">
        <span className="trend-wait-dot" aria-hidden="true" />
        Collecting telemetry samples…
      </div>
    );
  }
  const coords = values.map((value, index) => {
    const x = (index * 600) / (values.length - 1);
    const y = 104 - Math.max(0, Math.min(100, value)) * 0.94;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const points = coords.join(" ");
  const lastCoord = coords[coords.length - 1].split(",");

  return (
    <svg
      className="resource-trend"
      viewBox="0 0 600 110"
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.32" />
          <stop offset="100%" stopColor={color} stopOpacity="0.0" />
        </linearGradient>
      </defs>
      {[10, 33, 57, 80, 104].map((y) => (
        <line
          key={y}
          x1="0"
          y1={y}
          x2="600"
          y2={y}
          stroke="rgba(15, 23, 42, 0.08)"
          strokeDasharray="4 6"
        />
      ))}
      <polygon points={`0,110 ${points} 600,110`} fill={`url(#${gradientId})`} />
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle
        cx={lastCoord[0]}
        cy={lastCoord[1]}
        r="3.5"
        fill={color}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

export default function SystemMonitor({ compact = false }: { compact?: boolean }) {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [history, setHistory] = useState<Metrics[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let timer: number;
    async function refresh() {
      try {
        const sample = await api<Metrics>("/system/metrics", { signal: controller.signal });
        if (controller.signal.aborted) return;
        setMetrics(sample);
        setHistory((items) => [...items, sample].slice(-60));
        setError("");
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Metrics unavailable");
        }
      } finally {
        if (!controller.signal.aborted) timer = window.setTimeout(refresh, 5000);
      }
    }
    void refresh();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, []);

  const cards = metrics
    ? [
        {
          name: "CPU utilization",
          tag: "CPU",
          value: metrics.cpu.percent,
          detail: `${metrics.cpu.physical_cores ?? "—"} cores · ${metrics.cpu.logical_cores ?? "—"} logical processors`,
          color: "blue",
        },
        {
          name: "Memory in use",
          tag: "RAM",
          value: metrics.memory.percent,
          detail: `${gigabytes(metrics.memory.used_bytes)} / ${gigabytes(metrics.memory.total_bytes)} used`,
          color: "violet",
        },
        {
          name: "Recording drive",
          tag: "DISK",
          value: metrics.disk.percent,
          detail: `${gigabytes(metrics.disk.free_bytes)} free of ${gigabytes(metrics.disk.total_bytes)}`,
          color: "mint",
        },
      ]
    : [];

  return (
    <section className="system-monitor" aria-label="Server system resources">
      <div className="section-title">
        <div>
          <h2>System resources</h2>
          <p>
            Backend host ·{" "}
            {compact ? "Current resource usage" : "Live samples every 5 seconds"}
          </p>
        </div>
        <span className={`sample-status ${error ? "stale" : ""}`}>
          <i aria-hidden="true" />
          {error
            ? "Update unavailable"
            : metrics
              ? `Updated ${new Date(metrics.sampled_at * 1000).toLocaleTimeString()}`
              : "Connecting…"}
        </span>
      </div>

      {error && (
        <div className="error" role="alert">
          {error}. Retrying automatically.
          {metrics && " Values below are from the last successful sample."}
        </div>
      )}

      {!metrics && !error && (
        <div className="metrics-loading">
          <div className="skeleton-cards" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <p>Reading CPU, memory and storage usage…</p>
        </div>
      )}

      <div className="resource-grid">
        {cards.map((card, index) => (
          <article
            className={`resource-card ${card.color}`}
            key={card.tag}
            style={{ "--stagger": index } as CSSProperties}
          >
            <div className="resource-label">
              <span>{card.name}</span>
              <b>{card.tag}</b>
            </div>
            <div className="resource-value">
              {card.value.toFixed(1)}
              <span>%</span>
              <small className={card.value >= 85 ? "usage-high" : ""}>
                {card.value >= 85 ? "High usage" : "Nominal"}
              </small>
            </div>
            <div
              className="meter-track"
              role="progressbar"
              aria-label={`${card.name}: ${card.value.toFixed(1)}%`}
              aria-valuenow={Math.round(card.value)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className="meter-fill"
                style={{ width: `${Math.max(2, Math.min(100, card.value))}%` }}
              />
            </div>
            <p>{card.detail}</p>
          </article>
        ))}
      </div>

      {!compact && metrics && (
        <>
          <div className="trend-grid">
            <article className="panel trend-panel">
              <div className="section-title">
                <h2>CPU activity</h2>
                <span className="trend-badge blue">0–100%</span>
              </div>
              <Trend
                values={history.map((sample) => sample.cpu.percent)}
                label="CPU usage from this viewing session"
                color="#0284c7"
              />
              <div className="trend-caption">
                <span>Session trend · {history.length} samples</span>
                <span>Live</span>
              </div>
            </article>
            <article className="panel trend-panel">
              <div className="section-title">
                <h2>Memory activity</h2>
                <span className="trend-badge violet">0–100%</span>
              </div>
              <Trend
                values={history.map((sample) => sample.memory.percent)}
                label="Memory usage from this viewing session"
                color="#7c3aed"
              />
              <div className="trend-caption">
                <span>Session trend · {history.length} samples</span>
                <span>Live</span>
              </div>
            </article>
          </div>
          <div className="host-facts panel">
            <div>
              <span>Host uptime</span>
              <strong>{uptime(metrics.host_uptime_seconds)}</strong>
            </div>
            <div>
              <span>API process uptime</span>
              <strong>{uptime(metrics.api_uptime_seconds)}</strong>
            </div>
            <div>
              <span>API process memory</span>
              <strong>{Math.round(metrics.api_memory_bytes / 1024 ** 2)} MB</strong>
            </div>
            <div>
              <span>Available RAM</span>
              <strong>{gigabytes(metrics.memory.available_bytes)}</strong>
            </div>
          </div>
          <p className="camera-note">
            CPU and RAM include all applications on the backend host. Disk usage covers the entire
            volume containing recordings. Charts retain up to 60 samples while this page is open.
          </p>
        </>
      )}
    </section>
  );
}
