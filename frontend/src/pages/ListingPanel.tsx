import { useEffect, useState } from "react";
import { api } from "../api";
import CitationChip from "../components/CitationChip";
import StatusBadge, { STATUS_LABEL } from "../components/StatusBadge";
import JobProgress from "../components/JobProgress";
import { AdvisoryNote, Alert, Button, RunInfo, Spinner } from "../components/ui";
import { useJob } from "../useJob";
import type { Citation, ListingMatch, ListingResult, SourceTarget } from "../types";

type OnCite = (t: SourceTarget, c: Citation) => void;

export default function ListingPanel({ claimId, onCite }: { claimId: number; onCite: OnCite }) {
  const [data, setData] = useState<ListingMatch | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.get<ListingMatch | null>(`/api/claims/${claimId}/listing-match`).then(setData).catch((e) => setErr(e.message)); }, [claimId]);

  const [jobId, setJobId] = useState<number | null>(null);
  const job = useJob(jobId, (j) => { setBusy(false); if (j.status === "done") api.get<never>(`/api/claims/${claimId}/listing-match`).then(setData); else setErr(j.message); });
  async function run() {
    setBusy(true); setErr(null);
    try { setJobId((await api.post<{ job_id: number }>(`/api/claims/${claimId}/listing-match`)).job_id); } catch (e) { setErr((e as Error).message); setBusy(false); }
  }

  const met = data?.listings.filter((l) => l.overall === "criteria_appear_met") ?? [];
  const others = data?.listings.filter((l) => l.overall !== "criteria_appear_met") ?? [];

  return (
    <div>
      {data && <SummaryBanner data={data} />}
      <AdvisoryNote>
        Compares the evidence to the most relevant musculoskeletal listings (1.15–1.23), quoted verbatim from SSA's Blue Book.
        Every quote is checked twice: that it appears on the cited page, and that it actually supports the criterion.
        A "Met" or "Not met" call without a verified, relevant citation is shown as insufficient evidence.
      </AdvisoryNote>
      <div className="mb-3 flex items-center gap-3">
        <Button onClick={run} disabled={busy}>{data ? "Re-run listing comparison" : "Compare to listings"}</Button>
      </div>
      {busy && <JobProgress job={job} title="Listing comparison" />}
      {err && <Alert type="error" title="Listing comparison failed">{err}</Alert>}
      {data === undefined && <Spinner label="Loading…" />}
      {data && (
        <>
          <RunInfo run={data.run} />
          <p className="my-2 text-sm">
            <b>Citation check:</b> {data.verification.verified} of {data.verification.citations} quotes found on the cited page
            {data.verification.relevant != null && <> · {data.verification.relevant} judged relevant</>}
            {!!data.verification.not_relevant && <span className="ml-1 font-bold text-[#8a5a00]">· {data.verification.not_relevant} may not support their claim</span>}
            {data.verification.unverified > 0 && <span className="ml-1 font-bold text-[#b50909]">· {data.verification.unverified} unverified</span>}
          </p>
          {met.length > 0 ? (
            <>
              {met.map((l) => <ListingCard key={l.run_id} l={l} onCite={onCite} defaultOpen />)}
              {others.length > 0 && (
                <details className="mb-4 border border-gray-300 bg-white">
                  <summary className="cursor-pointer p-3 text-sm font-bold">Other listings reviewed ({others.map((o) => o.listing_code).join(", ")}): not applicable</summary>
                  <div className="p-3 pt-0">{others.map((l) => <ListingCard key={l.run_id} l={l} onCite={onCite} defaultOpen={false} />)}</div>
                </details>
              )}
            </>
          ) : (
            data.listings.map((l) => <ListingCard key={l.run_id} l={l} onCite={onCite} defaultOpen={!l.gate} />)
          )}
        </>
      )}
    </div>
  );
}

function SummaryBanner({ data }: { data: ListingMatch }) {
  const b = data.banner;
  return (
    <div role="status" className={`mb-3 border-l-8 p-3 ${b.any_met ? "border-[#00a91c] bg-[#ecf3ec]" : "border-gray-500 bg-gray-100"}`}>
      {b.any_met ? (
        <p className="text-base font-bold">
          Appears to meet listing {b.met.map((m) => `${m.code} (${m.name})`).join("; ")}.{" "}
          <span className="font-normal">Other listings reviewed: not applicable.</span>
        </p>
      ) : (
        <p className="text-base font-bold">
          No listing appears met. <span className="font-normal">Next: consider medical equivalence and residual functional capacity (RFC) assessment.</span>
        </p>
      )}
      <p className="mt-1 text-xs text-gray-800">Not meeting a listing does not mean the claim should be denied. Examiners make all determinations.</p>
    </div>
  );
}

function ListingCard({ l, onCite, defaultOpen }: { l: ListingResult; onCite: OnCite; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const [showText, setShowText] = useState(false);

  if (!open) {
    return (
      <section className="mb-2 flex flex-wrap items-center gap-2 border border-gray-300 bg-white px-3 py-2 text-sm" aria-label={`Listing ${l.listing_code} (collapsed)`}>
        <b>{l.listing_code}</b> <span className="text-gray-800">{l.name}</span>
        <StatusBadge status={l.overall} listing />
        {l.gate && <span className="text-xs text-gray-800">Required criterion {l.gate.criterion_id} ({l.gate.body.replace(/[.;:]$/, "")}) not met.</span>}
        <button className="ml-auto text-xs font-semibold text-[#005ea2] underline" onClick={() => setOpen(true)} aria-expanded={false}>Show criteria</button>
      </section>
    );
  }

  return (
    <section className="mb-5 border border-gray-400 bg-white" aria-labelledby={`l-${l.run_id}`}>
      <header className="border-b border-gray-300 bg-gray-50 p-3">
        <div className="flex flex-wrap items-start gap-2">
          <h3 id={`l-${l.run_id}`} className="text-base font-bold">{l.listing_code} {l.name}</h3>
          <button className="ml-auto text-xs font-semibold text-[#005ea2] underline" onClick={() => setOpen(false)} aria-expanded>Collapse</button>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
          <span>AI assessment:</span> <StatusBadge status={l.overall} listing />
          <span className="text-xs text-gray-600">Requires {l.logic === "any" ? "any one of" : "all of"} the lettered criteria · retrieval similarity {l.retrieval_score.toFixed(2)}</span>
        </div>
        {l.gate && <p className="mt-1 text-sm">Required criterion <b>{l.gate.criterion_id}</b> is not met: {l.gate.rationale}</p>}
        {l.overall_adjusted && (
          <p className="mt-1 text-xs font-semibold text-gray-800">
            Result computed from the criterion rows below (the AI's own overall call was "{STATUS_LABEL(l.ai_overall)}").
          </p>
        )}
        <p className="mt-1 text-sm text-gray-900">{l.overall_rationale}</p>
        <p className="mt-1 text-xs">
          Source: <a className="text-[#005ea2] underline" href={`${l.source_url}#${l.listing_code.replace(".", "_")}`} target="_blank" rel="noreferrer">SSA Blue Book, listing {l.listing_code}</a>
          {" "}· retrieved {new Date(l.fetched_at).toLocaleDateString()} ·{" "}
          <button className="text-[#005ea2] underline" onClick={() => setShowText(!showText)} aria-expanded={showText}>{showText ? "Hide" : "Show"} verbatim listing text</button>
        </p>
        {showText && <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap border border-gray-300 bg-white p-2 text-xs">{l.listing_text}</pre>}
      </header>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">Criterion-by-criterion assessment for listing {l.listing_code}</caption>
          <thead>
            <tr className="border-b-2 border-gray-800 text-left">
              <th scope="col" className="w-2/5 p-2">Criterion (SSA text)</th>
              <th scope="col" className="p-2">AI assessment</th>
              <th scope="col" className="w-2/5 p-2">Rationale and evidence</th>
            </tr>
          </thead>
          <tbody>
            {l.criteria.map((r) => (
              <tr key={r.criterion_id} className={`border-b border-gray-200 align-top ${r.level === "criterion" ? "bg-white" : "bg-gray-50"}`}>
                <td className={`p-2 ${r.level === "subcriterion" ? "pl-6 text-gray-800" : "font-semibold"}`}>
                  <span className="mr-1.5 font-mono text-xs font-bold text-gray-700">{r.criterion_id}</span>{r.body}
                </td>
                <td className="p-2">
                  <StatusBadge status={r.status} />
                  {r.ai_status && r.ai_status !== r.status && <p className="mt-1 text-xs text-gray-700">AI said: {STATUS_LABEL(r.ai_status)}</p>}
                </td>
                <td className="p-2">
                  <p>{r.rationale}</p>
                  {r.note && <p className="text-xs font-semibold text-[#8b0a03]">{r.note}</p>}
                  {r.citations.map((c) => <CitationChip key={c.id} c={c} onOpen={onCite} />)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
