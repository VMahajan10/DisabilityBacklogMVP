import { useEffect, useState } from "react";
import { api } from "../api";
import CitationChip from "../components/CitationChip";
import JobProgress from "../components/JobProgress";
import { AdvisoryNote, Alert, Button, RunInfo, Spinner } from "../components/ui";
import { useJob } from "../useJob";
import type { Citation, MissingEvidence, SourceTarget } from "../types";

const FLAG_LABEL: Record<string, string> = {
  no_recent_imaging: "No recent imaging",
  no_treating_source_opinion: "No treating source opinion",
  stale_records: "Records out of date",
  listing_criteria_undocumented: "Listing criteria undocumented",
  consultative_exam_needed: "Consultative exam needed",
  missing_test: "Test needed",
  missing_specialist_records: "Specialist records missing",
  insufficient_exam_detail: "Exam lacks detail",
  other: "Other gap",
};
const SOURCE_LABEL = { rule: "Rule-based check", ai: "AI-identified", listing_match: "From listing comparison" };

export default function MissingPanel({ claimId, onCite, onChange }: { claimId: number; onCite: (t: SourceTarget, c: Citation) => void; onChange: () => void }) {
  const [data, setData] = useState<MissingEvidence | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [letter, setLetter] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [showItems, setShowItems] = useState(false);

  const apply = (d: MissingEvidence | null) => { setData(d); setLetter(d?.letter ? d.letter.edited_text ?? d.letter.draft_text : ""); };
  useEffect(() => { api.get<MissingEvidence | null>(`/api/claims/${claimId}/missing-evidence`).then(apply).catch((e) => setErr(e.message)); }, [claimId]);

  const [jobId, setJobId] = useState<number | null>(null);
  const job = useJob(jobId, (j) => { setBusy(false); if (j.status === "done") api.get<never>(`/api/claims/${claimId}/missing-evidence`).then((d) => { apply(d); onChange(); }); else setErr(j.message); });
  async function run() {
    setBusy(true); setErr(null);
    try { setJobId((await api.post<{ job_id: number }>(`/api/claims/${claimId}/missing-evidence`)).job_id); } catch (e) { setErr((e as Error).message); setBusy(false); }
  }
  async function save() {
    try { await api.put(`/api/claims/${claimId}/records-request`, { text: letter }); setSaved("Saved. Your edits are recorded in the audit trail."); onChange(); }
    catch (e) { setErr((e as Error).message); }
  }

  return (
    <div>
      <AdvisoryNote>
        Flags possible evidence gaps. Rule-based checks use dates from verified citations only (imaging within {data?.thresholds?.imaging_recency_months ?? 12} months of filing; exam within {data?.thresholds?.stale_record_months ?? 12} months).
        The letter is a draft for you to edit; nothing is sent.
      </AdvisoryNote>
      <div className="mb-3 flex items-center gap-3">
        <Button onClick={run} disabled={busy}>{data ? "Re-check evidence" : "Check for missing evidence"}</Button>
      </div>
      {busy && <JobProgress job={job} title="Missing-evidence check" />}
      {err && <Alert type="error" title="Error">{err}</Alert>}
      {data === undefined && <Spinner label="Loading…" />}
      {data && (
        <>
          <RunInfo run={data.run} />
          <h3 className="mt-3 mb-1 border-b border-gray-400 text-base font-bold">Evidence gaps ({data.flags.length})</h3>
          {data.flags.length === 0 ? <Alert type="success" title="No gaps flagged">The rule checks and AI review found no missing evidence.</Alert> : (
            <ul className="space-y-2">
              {data.flags.map((f, i) => (
                <li key={i} className="border-l-4 border-[#ffbe2e] bg-white px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <b>{FLAG_LABEL[f.type] ?? f.type}</b>
                    <span className="rounded border border-gray-500 px-1 text-xs">{SOURCE_LABEL[f.source]}</span>
                  </div>
                  <p>{f.explanation}</p>
                  <p className="text-xs text-gray-700"><b>Suggested:</b> {f.suggested_action}</p>
                  {f.citations.map((c) => <CitationChip key={c.id} c={c} onOpen={onCite} />)}
                </li>
              ))}
            </ul>
          )}
          <button className="mt-3 text-sm font-semibold text-[#005ea2] underline" onClick={() => setShowItems(!showItems)} aria-expanded={showItems}>
            {showItems ? "Hide" : "Show"} evidence inventory ({data.evidence_items.length} items)
          </button>
          {showItems && (
            <table className="mt-2 w-full border-collapse bg-white text-xs">
              <thead><tr className="border-b-2 border-gray-800 text-left"><th className="p-1">Date</th><th className="p-1">Type</th><th className="p-1">Source</th><th className="p-1">Exam?</th><th className="p-1">Evidence</th></tr></thead>
              <tbody>
                {data.evidence_items.map((it, i) => (
                  <tr key={i} className={`border-b border-gray-200 align-top ${it.verified ? "" : "bg-red-50"}`}>
                    <td className="p-1 whitespace-nowrap">{it.date ?? "—"}</td>
                    <td className="p-1">{it.category.replace(/_/g, " ")}</td>
                    <td className="p-1">{it.source}</td>
                    <td className="p-1">{it.includes_musculoskeletal_or_neuro_exam ? "Yes" : "No"}</td>
                    <td className="p-1">{it.description}{!it.verified && <b className="ml-1 text-[#8b0a03]">(unverified, excluded from rule checks)</b>}
                      {it.citations.map((c) => <CitationChip key={c.id} c={c} onOpen={onCite} />)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {data.letter && (
            <section className="mt-4" aria-labelledby="letter-h">
              <h3 id="letter-h" className="mb-1 border-b border-gray-400 text-base font-bold">Draft provider records request</h3>
              <p className="mb-1 text-xs text-gray-700">AI-drafted. Review and edit before use. {data.letter.edited_text ? "Showing your saved edits." : "Unedited draft."}</p>
              <label htmlFor="letter" className="sr-only">Records request letter</label>
              <textarea id="letter" value={letter} onChange={(e) => { setLetter(e.target.value); setSaved(null); }} rows={18}
                className="w-full rounded border border-gray-600 bg-white p-2 font-mono text-xs" />
              <div className="mt-1 flex items-center gap-3">
                <Button variant="outline" onClick={save}>Save letter</Button>
                {saved && <span role="status" className="text-sm text-[#00731d]">{saved}</span>}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
