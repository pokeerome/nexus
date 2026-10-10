import { useEffect, useState } from "react";
import { getUsage } from "../api";
import type { UsageStats } from "../api";

const LABELS: Record<string, string> = {
  chat: "Chat questions",
  agent: "Agent questions",
  search: "Search",
  tool: "Agent tool calls",
  ingest: "Reading files",
};

function usd(n: number) {
  return n < 0.01 ? `$${n.toFixed(5)}` : `$${n.toFixed(3)}`;
}

function seconds(ms: number) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}

export default function Usage({ workspaceId }: { workspaceId: number }) {
  const [days, setDays] = useState(7);
  const [stats, setStats] = useState<UsageStats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;

    async function refresh() {
      if (document.hidden) {
        timeoutId = setTimeout(refresh, 30_000);
        return;
      }

      try {
        const data = await getUsage(workspaceId, days);
        if (!cancelled) {
          setStats(data);
          setError("");
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) {
          timeoutId = setTimeout(refresh, 30_000);
        }
      }
    }

    void refresh();

    return () => {
      cancelled = true;
      if (timeoutId !== undefined) clearTimeout(timeoutId);
    };
  }, [workspaceId, days]);

  return (
    <div className="bg-slate-800 p-6 rounded-xl">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">Usage</h2>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="p-1 rounded bg-slate-700 text-white text-sm"
        >
          <option value={1}>Last day</option>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
        </select>
      </div>

      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      {stats && (
        <>
          <div className="grid grid-cols-4 gap-3 mb-4 text-center">
            <div className="bg-slate-700 rounded p-3">
              <div className="text-xl font-semibold">{stats.total.requests}</div>
              <div className="text-slate-400 text-xs">requests</div>
            </div>
            <div className="bg-slate-700 rounded p-3">
              <div className="text-xl font-semibold">{stats.total.errors}</div>
              <div className="text-slate-400 text-xs">errors</div>
            </div>
            <div className="bg-slate-700 rounded p-3">
              <div className="text-xl font-semibold">{stats.total.tokens.toLocaleString()}</div>
              <div className="text-slate-400 text-xs">tokens</div>
            </div>
            <div className="bg-slate-700 rounded p-3">
              <div className="text-xl font-semibold">{usd(stats.total.cost_usd)}</div>
              <div className="text-slate-400 text-xs">estimated cost</div>
            </div>
          </div>

          {stats.by_kind.length === 0 ? (
            <p className="text-slate-400 text-sm">No activity in this period.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-slate-400 text-left">
                <tr>
                  <th className="pb-2 font-normal">What</th>
                  <th className="pb-2 font-normal text-right">Count</th>
                  <th className="pb-2 font-normal text-right">Average</th>
                  <th className="pb-2 font-normal text-right">Slowest 5%</th>
                  <th className="pb-2 font-normal text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {stats.by_kind.map((k) => (
                  <tr key={k.kind} className="border-t border-slate-700">
                    <td className="py-2">{LABELS[k.kind] ?? k.kind}</td>
                    <td className="py-2 text-right">
                      {k.requests}
                      {k.errors > 0 && <span className="text-red-400"> ({k.errors} failed)</span>}
                    </td>
                    <td className="py-2 text-right">{seconds(k.avg_ms)}</td>
                    <td className="py-2 text-right">{seconds(k.p95_ms)}</td>
                    <td className="py-2 text-right">{usd(k.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="text-slate-500 text-xs mt-3">
            Costs are estimates from OpenAI list prices. Questions and file text are never stored here.
          </p>
        </>
      )}
    </div>
  );
}
