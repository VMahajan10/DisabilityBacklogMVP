import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import JobProgress from "../components/JobProgress";
import { useJob } from "../useJob";
import SourceViewer from "../components/SourceViewer";
import { Alert, Spinner } from "../components/ui";
import type { Citation, ClaimDetail, Job, SourceTarget } from "../types";
import AuditPanel from "./AuditPanel";
import { DECISION_LABEL, QUEUE_LABEL } from "../labels";
import ListingPanel from "./ListingPanel";
import MissingPanel from "./MissingPanel";
import TriagePanel from "./TriagePanel";
import TimelinePanel from "./TimelinePanel";
import DecisionPanel from "./DecisionPanel";
import SummaryPanel from "./SummaryPanel";

const TABS = [
  { key: "summary", label: "Evidence summary" },
  { key: "timeline", label: "Timeline & conflicts" },
  { key: "listings", label: "Listing match" },
  { key: "missing", label: "Missing evidence" },
  { key: "triage", label: "Triage" },
  { key: "decision", label: "Examiner decision" },
  { key: "audit", label: "Audit trail" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

export default function CaseView() {
  const id = Number(useParams().id);
  const [claim, setClaim] = useState<ClaimDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();
  const tab = (TABS.some((t) => t.key === params.get("tab")) ? params.get("tab") : "summary") as TabKey;
  const setTab = (k: TabKey) => setParams({ tab: k }, { replace: true });
  const [target, setTarget] = useState<SourceTarget | null>(null);
  const [auditKey, setAuditKey] = useState(0);

  const reload = useCallback(() => api.get<ClaimDetail>(`/api/claims/${id}`).then(setClaim).catch((e) => setErr(e.message)), [id]);
  useEffect(() => { reload(); }, [reload]);
  const [ingestJobId, setIngestJobId] = useState<number | null>(null);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  useEffect(() => {
    api.get<Job[]>(`/api/claims/${id}/jobs`).then((jobs) => {
      const j = jobs.find((x) => x.kind === "ingest");
      if (j && (j.status !== "done" || Date.now() - Date.parse(j.finished_at ?? "") < 15000)) setIngestJobId(j.id);
    }).catch(() => undefined);
  }, [id]);
  const ingestJob = useJob(ingestJobId, () => { reload(); setAuditKey((k) => k + 1); });

  async function addDocuments(files: FileList | null) {
    if (!files?.length) return;
    setUploadErr(null);
    try {
      const r = await api.upload<{ job_id: number }>(`/api/claims/${id}/documents`, files);
      setIngestJobId(r.job_id);
      reload();
    } catch (e) { setUploadErr((e as Error).message); }
  }

  const onCite = useCallback((t: SourceTarget, c: Citation) => {
    setTarget(t);
    api.logEvent(id, "citation_viewed", { citation_id: c.id, doc_id: c.doc_id, doc_label: c.doc_label, page: c.page, verified: c.verified });
  }, [id]);

  const bump = useCallback(() => { setAuditKey((k) => k + 1); reload(); }, [reload]);

  if (err) return <div className="p-6"><Alert type="error" title="Could not load claim">{err}</Alert></div>;
  if (!claim) return <div className="p-6"><Spinner label="Loading claim…" /></div>;

  return (
    <div className="flex h-[calc(100vh-6.5rem)] flex-col">
      <div className="border-b border-gray-300 bg-white px-4 py-2">
        <Link to="/" className="text-sm text-[#005ea2] underline">← All cases</Link>
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
          <h1 className="text-xl font-bold">{claim.claimant_name}</h1>
          <span className="text-sm">Claim <b>{claim.claim_number}</b></span>
          <span className="text-sm">DOB {claim.dob ?? "—"}</span>
          <span className="text-sm">Alleged onset {claim.alleged_onset_date ?? "—"}</span>
          <span className="text-sm">Filed {claim.filed_date ?? "—"}</span>
          <span className="text-sm">Queue: <b>{claim.final_queue ? QUEUE_LABEL[claim.final_queue] : "unassigned"}</b>{claim.ai_suggested_queue && !claim.final_queue ? ` (AI suggests ${QUEUE_LABEL[claim.ai_suggested_queue]})` : ""}</span>
          <span className="text-sm">Decision: <b>{claim.decision ? DECISION_LABEL[claim.decision] : "pending"}</b></span>
          <span className="text-sm">{claim.documents.length} documents · {claim.page_count} pages</span>
          <label className="ml-auto cursor-pointer rounded border-2 border-[#005ea2] bg-white px-3 py-1 text-sm font-bold text-[#005ea2] hover:bg-blue-50 focus-within:outline focus-within:outline-2 focus-within:outline-[#2491ff]">
            + Add documents
            <input type="file" accept="application/pdf" multiple className="sr-only" onChange={(e) => { addDocuments(e.target.files); e.target.value = ""; }}
              disabled={ingestJob?.status === "running"} />
          </label>
        </div>
        {uploadErr && <p className="text-sm font-semibold text-[#b50909]">{uploadErr}</p>}
        <JobProgress job={ingestJob} title="Document intake" />
        {claim.processing && <p className="text-xs text-gray-700">AI tools will use the new documents once processing finishes.</p>}
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-2">
        <section aria-label="AI assistance" className="flex min-h-0 flex-col border-r-2 border-gray-400 bg-gray-50">
          <div role="tablist" aria-label="Case tools" className="flex flex-wrap border-b border-gray-400 bg-white">
            {TABS.map((t) => (
              <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => { setTab(t.key); if (t.key === "audit") setAuditKey((k) => k + 1); }}
                className={`px-3 py-2 text-sm font-bold ${tab === t.key ? "border-b-4 border-[#005ea2] text-[#005ea2]" : "border-b-4 border-transparent text-gray-700 hover:text-black"}`}>
                {t.label}
              </button>
            ))}
          </div>
          <div role="tabpanel" className="min-h-0 flex-1 overflow-auto p-4">
            {tab === "summary" && <SummaryPanel claimId={id} onCite={onCite} />}
            {tab === "timeline" && <TimelinePanel claimId={id} onCite={onCite} refreshKey={auditKey} />}
            {tab === "listings" && <ListingPanel claimId={id} onCite={onCite} />}
            {tab === "missing" && <MissingPanel claimId={id} onCite={onCite} onChange={bump} />}
            {tab === "triage" && <TriagePanel claimId={id} onCite={onCite} onChange={bump} />}
            {tab === "decision" && <DecisionPanel claimId={id} onChange={bump} />}
            {tab === "audit" && <AuditPanel claimId={id} refreshKey={auditKey} />}
          </div>
        </section>
        <section aria-label="Source documents" className="min-h-0 bg-white">
          <SourceViewer docs={claim.documents} target={target} onNavigate={setTarget} />
        </section>
      </div>
    </div>
  );
}
