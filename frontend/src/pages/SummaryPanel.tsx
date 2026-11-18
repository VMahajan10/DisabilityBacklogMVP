import { useEffect, useState } from "react";
import { api } from "../api";
import CitationChip from "../components/CitationChip";
import JobProgress from "../components/JobProgress";
import { AdvisoryNote, Alert, Button, RunInfo, Spinner } from "../components/ui";
import { useJob } from "../useJob";
import type { Citation, SourceTarget, Summary } from "../types";

export default function SummaryPanel({ claimId, onCite }: { claimId: number; onCite: (t: SourceTarget, c: Citation) => void }) {
  const [data, setData] = useState<Summary | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const load = () => api.get<Summary | null>(`/api/claims/${claimId}/summary`).then(setData).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [claimId]); // eslint-disable-line react-hooks/exhaustive-deps
  const job = useJob(jobId, (j) => { setBusy(false); if (j.status === "done") load(); else setErr(j.message); });

  async function run() {
    setBusy(true); setErr(null);
    try { setJobId((await api.post<{ job_id: number }>(`/api/claims/${claimId}/summary`)).job_id); } catch (e) { setErr((e as Error).message); setBusy(false); }
  }

  return (
    <div>
      <AdvisoryNote>AI-generated summary of the evidence. Each statement cites its source page. Statements whose quote could not be found on the cited page are marked <b>Unverified</b> and must not be relied on.</AdvisoryNote>
      <div className="mb-3 flex items-center gap-3">
        <Button onClick={run} disabled={busy}>{data ? "Regenerate summary" : "Generate evidence summary"}</Button>
      </div>
      {busy && <JobProgress job={job} title="Evidence summary" />}
      {err && <Alert type="error" title="Summary failed">{err}</Alert>}
      {data === undefined && <Spinner label="Loading…" />}
      {data && (
        <>
          <RunInfo run={data.run} />
          {data.stats && (
            <p className="text-xs text-gray-700">
              Map-reduce: {data.stats.pages_in_scope} pages in scope (duplicates and administrative pages excluded) · {data.stats.map_batches} batches summarized
              {data.map_model ? ` with ${data.map_model}` : ""} · {data.stats.map_bullets_verified} verified facts combined
            </p>
          )}
          <p className="my-2 text-sm">
            <b>Citation check:</b> {data.verification.verified} of {data.verification.citations} quotes found on the cited page
            {data.verification.unverified > 0 && <span className="ml-1 font-bold text-[#b50909]">· {data.verification.unverified} unverified</span>}
          </p>
          {data.sections.map((s) => (
            <section key={s.key} className="mb-4" aria-labelledby={`sec-${s.key}`}>
              <h3 id={`sec-${s.key}`} className="mb-1 border-b border-gray-400 text-base font-bold">{s.title}</h3>
              {s.bullets.length === 0 ? <p className="text-sm italic text-gray-600">No evidence found in the file for this section.</p> : (
                <ul className="space-y-2">
                  {s.bullets.map((b, i) => <BulletItem key={i} b={b} onCite={onCite} />)}
                </ul>
              )}
            </section>
          ))}
        </>
      )}
    </div>
  );
}

function BulletItem({ b, onCite }: { b: Summary["sections"][0]["bullets"][0]; onCite: (t: SourceTarget, c: Citation) => void }) {
  const [open, setOpen] = useState(false);
  if (!b.verified) {
    return (
      <li className="border-l-4 border-[#b50909] bg-red-50 px-3 py-2 text-sm">
        <p className="font-bold text-[#8b0a03]">⚠ Unverified — do not rely on this statement.</p>
        <button className="text-xs font-semibold text-[#8b0a03] underline" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Hide" : "Show"} unverified AI text
        </button>
        {open && (
          <div className="mt-1 text-gray-800">
            <p className="line-through decoration-1">{b.text}</p>
            {b.citations.map((c) => <CitationChip key={c.id} c={c} onOpen={onCite} />)}
          </div>
        )}
      </li>
    );
  }
  return (
    <li className="border-l-4 border-[#005ea2] bg-white px-3 py-2 text-sm">
      <p>{b.text}</p>
      {b.citations.map((c) => <CitationChip key={c.id} c={c} onOpen={onCite} />)}
    </li>
  );
}
