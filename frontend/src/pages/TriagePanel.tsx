import { useEffect, useState } from "react";
import { api } from "../api";
import CitationChip from "../components/CitationChip";
import JobProgress from "../components/JobProgress";
import { AdvisoryNote, Alert, Button, RunInfo, Spinner } from "../components/ui";
import { useJob } from "../useJob";
import type { Citation, SourceTarget, Triage } from "../types";
import { QUEUE_LABEL } from "../labels";

const QUEUE_STYLE: Record<string, string> = {
  fast_track: "border-[#00a91c] bg-[#ecf3ec]",
  standard: "border-[#005ea2] bg-[#e7f6f8]",
  senior_examiner: "border-[#c2850c] bg-[#faf3d1]",
};

export default function TriagePanel({ claimId, onCite, onChange }: { claimId: number; onCite: (t: SourceTarget, c: Citation) => void; onChange: () => void }) {
  const [data, setData] = useState<Triage | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [choice, setChoice] = useState("");
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const apply = (d: Triage | null) => { setData(d); setChoice(d?.assignment?.final_queue ?? d?.suggested_queue ?? ""); setReason(d?.assignment?.override_reason ?? ""); };
  useEffect(() => { api.get<Triage | null>(`/api/claims/${claimId}/triage`).then(apply).catch((e) => setErr(e.message)); }, [claimId]);

  const [jobId, setJobId] = useState<number | null>(null);
  const job = useJob(jobId, (j) => { setBusy(false); if (j.status === "done") api.get<never>(`/api/claims/${claimId}/triage`).then((d) => { apply(d); onChange(); }); else setErr(j.message); });
  async function run() {
    setBusy(true); setErr(null);
    try { setJobId((await api.post<{ job_id: number }>(`/api/claims/${claimId}/triage`)).job_id); } catch (e) { setErr((e as Error).message); setBusy(false); }
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setErr(null);
    try {
      await api.put(`/api/claims/${claimId}/queue`, { final_queue: choice, override_reason: reason || null });
      setMsg(choice === data?.suggested_queue ? "Suggestion accepted." : "Override recorded.");
      apply(await api.get<Triage>(`/api/claims/${claimId}/triage`)); onChange();
    } catch (e) { setErr((e as Error).message); }
  }
  const overriding = data && choice !== data.suggested_queue;

  return (
    <div>
      <AdvisoryNote>
        Suggests a work queue. The AI only identifies cited signals (Compassionate Allowances match, conflicting opinions); fixed rules map them to a queue.
        Missing steps (summary, listing comparison) run automatically. <b>You assign the final queue.</b>
      </AdvisoryNote>
      <div className="mb-3 flex items-center gap-3">
        <Button onClick={run} disabled={busy}>{data ? "Re-run triage" : "Suggest triage queue"}</Button>
      </div>
      {busy && <JobProgress job={job} title="Triage" />}
      {err && <Alert type="error" title="Error">{err}</Alert>}
      {data === undefined && <Spinner label="Loading…" />}
      {data && (
        <>
          <RunInfo run={data.run} />
          <div className={`mt-3 border-l-8 p-3 ${QUEUE_STYLE[data.suggested_queue]}`}>
            <p className="text-xs font-bold uppercase tracking-wide">Suggested queue (advisory)</p>
            <p className="text-xl font-bold">{QUEUE_LABEL[data.suggested_queue]}</p>
            <ul className="mt-1 list-disc pl-5 text-sm">{data.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </div>
          <h3 className="mt-4 mb-1 border-b border-gray-400 text-base font-bold">Signals</h3>
          <div className="space-y-2 text-sm">
            <div className="bg-white p-2">
              <b>Compassionate Allowances:</b>{" "}
              {data.cal.verified_match ? <span className="font-bold text-[#00731d]">Match: {data.cal.verified_match}</span>
                : data.cal.matched ? <span className="font-bold text-[#8b0a03]">AI proposed "{data.cal.cal_condition}" but it could not be verified; not used.</span>
                : "No CAL condition identified."}
              <p className="text-xs text-gray-700">{data.cal.reasoning}</p>
              {data.cal.citations.map((c) => <CitationChip key={c.id} c={c} onOpen={onCite} />)}
              <details className="text-xs"><summary className="cursor-pointer text-[#005ea2]">CAL conditions compared (from SSA's list)</summary><ul className="list-disc pl-5">{data.cal.shortlist.map((s) => <li key={s}>{s}</li>)}</ul></details>
            </div>
            <div className="bg-white p-2">
              <b>Conflicting evidence:</b> {data.conflicts.length === 0 && "None identified."}
              {data.conflicts.map((c, i) => (
                <div key={i} className="mt-1">
                  <p>{c.description} {!c.verified && <b className="text-[#8b0a03]">(unverified; not used)</b>}</p>
                  {c.citations.map((x) => <CitationChip key={x.id} c={x} onOpen={onCite} />)}
                </div>
              ))}
            </div>
            {data.complexity_notes.length > 0 && <div className="bg-white p-2"><b>Other complexity:</b><ul className="list-disc pl-5">{data.complexity_notes.map((n, i) => <li key={i}>{n}</li>)}</ul></div>}
          </div>
          <form onSubmit={submit} className="mt-4 border-2 border-gray-800 bg-white p-3">
            <fieldset>
              <legend className="text-base font-bold">Examiner: assign queue</legend>
              {data.assignment?.decided_at && <p className="text-xs text-gray-700">Last assigned {new Date(data.assignment.decided_at).toLocaleString()}: {QUEUE_LABEL[data.assignment.final_queue!]}{data.assignment.overridden ? " (override)" : ""}</p>}
              {(["fast_track", "standard", "senior_examiner"] as const).map((q) => (
                <label key={q} className="mt-1 flex items-center gap-2 text-sm">
                  <input type="radio" name="queue" value={q} checked={choice === q} onChange={() => setChoice(q)} />
                  {QUEUE_LABEL[q]} {q === data.suggested_queue && <span className="text-xs text-gray-600">(AI suggestion)</span>}
                </label>
              ))}
              {overriding && (
                <div className="mt-2">
                  <label htmlFor="ovr" className="block text-sm font-bold">Reason for override (required)</label>
                  <textarea id="ovr" required value={reason} onChange={(e) => setReason(e.target.value)} rows={2} className="w-full rounded border border-gray-600 p-1 text-sm" />
                </div>
              )}
              <Button type="submit" className="mt-2">{overriding ? "Record override" : "Accept suggestion"}</Button>
              {msg && <span role="status" className="ml-3 text-sm text-[#00731d]">{msg}</span>}
            </fieldset>
          </form>
        </>
      )}
    </div>
  );
}
