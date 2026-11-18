import { useEffect, useState } from "react";
import { api } from "../api";
import { AdvisoryNote, Spinner } from "../components/ui";
import { DECISION_LABEL, QUEUE_LABEL } from "../labels";

type M = {
  include_seed: boolean;
  cases_total: number; cases_decided: number; cases_in_review: number;
  decisions: Record<string, number>;
  intake_to_decision_days: { median: number | null; mean: number | null; buckets: { label: string; n: number }[] };
  triage: { assigned: number; overridden: number; override_rate: number | null; suggested: Record<string, number>;
    matrix: { ai: string; final: string; n: number }[]; recent_overrides: { claim_number: string; ai: string; final: string; reason: string | null }[] };
  citations: { total: number; unverified: number; unverified_rate: number | null };
  listing_vs_decision: { ai: string; decision: string; n: number }[];
  weekly_decided: { week: string; decided: number }[];
};

const AI_LABEL: Record<string, string> = { criteria_appear_met: "Listing appears met", insufficient_evidence: "Insufficient evidence", criteria_not_met: "No listing met" };
const pct = (x: number | null) => (x == null ? "—" : `${(x * 100).toFixed(1)}%`);

export default function Metrics() {
  const [m, setM] = useState<M | null>(null);
  const [seed, setSeed] = useState(true);
  useEffect(() => { setM(null); api.get<M>(`/api/metrics?include_seed=${seed}`).then(setM); }, [seed]);

  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="mb-2 flex flex-wrap items-center gap-4">
        <h1 className="text-2xl font-bold">Pilot metrics</h1>
        <label className="ml-auto flex items-center gap-2 text-sm">
          <input type="checkbox" checked={seed} onChange={(e) => setSeed(e.target.checked)} /> Include seeded demo history
        </label>
      </div>
      <AdvisoryNote>{seed ? "Includes ~40 seeded demo claims (synthetic history for demonstration) plus claims processed in this prototype." : "Only claims processed in this prototype session."}</AdvisoryNote>
      {!m ? <Spinner label="Loading metrics…" /> : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Tile label="Cases in pilot" value={m.cases_total} sub={`${m.cases_in_review} in review`} />
            <Tile label="Cases decided" value={m.cases_decided} sub={Object.entries(m.decisions).map(([k, v]) => `${v} ${DECISION_LABEL[k].toLowerCase()}`).join(" · ")} />
            <Tile label="Median intake → decision" value={m.intake_to_decision_days.median == null ? "—" : `${m.intake_to_decision_days.median} days`} sub={`mean ${m.intake_to_decision_days.mean ?? "—"} days`} />
            <Tile label="Examiner overrides of AI triage" value={pct(m.triage.override_rate)} sub={`${m.triage.overridden} of ${m.triage.assigned} assigned`} />
            <Tile label="Unverified-citation rate" value={pct(m.citations.unverified_rate)} sub={`${m.citations.unverified} of ${m.citations.total.toLocaleString()} citations`} />
          </div>

          <div className="mt-6 grid gap-6 md:grid-cols-2">
            <Card title="Time from intake to decision" caption="Decided claims by elapsed days">
              <Bars rows={m.intake_to_decision_days.buckets.map((b) => ({ label: b.label, n: b.n }))} unit="claims" />
            </Card>
            <Card title="Claims decided per week" caption="By ISO week of decision">
              <Bars rows={m.weekly_decided.map((w) => ({ label: w.week, n: w.decided }))} unit="claims" />
            </Card>
          </div>

          <div className="mt-6 grid gap-6 md:grid-cols-2">
            <Card title="AI listing assessment vs examiner decision" caption="Top AI listing call for each claim (rows) against the examiner's final determination (columns). The AI never decides; this measures agreement.">
              <CrossTab rows={["criteria_appear_met", "insufficient_evidence", "criteria_not_met"]} cols={["allowed", "needs_development", "denied"]}
                rowLabel={(r) => AI_LABEL[r]} colLabel={(c) => DECISION_LABEL[c]} get={(r, c) => m.listing_vs_decision.find((x) => x.ai === r && x.decision === c)?.n ?? 0} />
            </Card>
            <Card title="AI triage suggestion vs examiner queue" caption="Off-diagonal cells are examiner overrides.">
              <CrossTab rows={["fast_track", "standard", "senior_examiner"]} cols={["fast_track", "standard", "senior_examiner"]}
                rowLabel={(r) => `AI: ${QUEUE_LABEL[r]}`} colLabel={(c) => QUEUE_LABEL[c]} get={(r, c) => m.triage.matrix.find((x) => x.ai === r && x.final === c)?.n ?? 0} diagonal />
              {m.triage.recent_overrides.length > 0 && (
                <>
                  <h3 className="mt-3 text-sm font-bold">Recent overrides</h3>
                  <ul className="text-xs">{m.triage.recent_overrides.map((o) => (
                    <li key={o.claim_number} className="border-b border-gray-200 py-1"><b>{o.claim_number}</b>: {QUEUE_LABEL[o.ai]} → {QUEUE_LABEL[o.final]}{o.reason ? ` — ${o.reason}` : ""}</li>
                  ))}</ul>
                </>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="border border-gray-300 bg-white p-3">
      <p className="text-xs font-bold uppercase tracking-wide text-gray-700">{label}</p>
      <p className="mt-1 text-3xl font-bold text-gray-900">{value}</p>
      {sub && <p className="mt-1 text-xs text-gray-700">{sub}</p>}
    </div>
  );
}

function Card({ title, caption, children }: { title: string; caption: string; children: React.ReactNode }) {
  return (
    <section className="border border-gray-300 bg-white p-4" aria-label={title}>
      <h2 className="text-lg font-bold">{title}</h2>
      <p className="mb-3 text-xs text-gray-700">{caption}</p>
      {children}
    </section>
  );
}

function Bars({ rows, unit }: { rows: { label: string; n: number }[]; unit: string }) {
  const max = Math.max(1, ...rows.map((r) => r.n));
  if (!rows.length) return <p className="text-sm text-gray-700">No data yet.</p>;
  return (
    <table className="w-full text-sm">
      <tbody>
        {rows.map((r) => (
          <tr key={r.label} className="group" title={`${r.label}: ${r.n} ${unit}`}>
            <th scope="row" className="w-28 py-1 pr-2 text-left font-normal text-gray-800">{r.label}</th>
            <td className="py-1">
              <div className="flex items-center gap-2">
                <div className="h-4 rounded-r bg-[#005ea2] group-hover:bg-[#1a4480]" style={{ width: `${(r.n / max) * 85}%`, minWidth: r.n ? 4 : 0 }} />
                <span className="text-xs text-gray-900">{r.n}</span>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CrossTab({ rows, cols, rowLabel, colLabel, get, diagonal }: { rows: string[]; cols: string[]; rowLabel: (r: string) => string; colLabel: (c: string) => string; get: (r: string, c: string) => number; diagonal?: boolean }) {
  const max = Math.max(1, ...rows.flatMap((r) => cols.map((c) => get(r, c))));
  const shade = (n: number) => {
    if (!n) return { background: "#f7f7f7", color: "#565c65" };
    const t = n / max;
    const steps = ["#d9e8f6", "#aacdec", "#73b3e7", "#2378c3", "#1a4480"];
    const i = Math.min(steps.length - 1, Math.floor(t * steps.length));
    return { background: steps[i], color: i >= 3 ? "#fff" : "#1b1b1b" };
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead><tr><th />{cols.map((c) => <th key={c} scope="col" className="p-1 text-xs font-bold">{colLabel(c)}</th>)}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r}>
              <th scope="row" className="p-1 pr-2 text-left text-xs font-bold">{rowLabel(r)}</th>
              {cols.map((c) => {
                const n = get(r, c);
                return (
                  <td key={c} className={`border-2 border-white p-2 text-center font-bold ${diagonal && r === c ? "outline outline-2 -outline-offset-4 outline-gray-900" : ""}`}
                    style={shade(n)} title={`${rowLabel(r)} → ${colLabel(c)}: ${n}`}>{n}</td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
