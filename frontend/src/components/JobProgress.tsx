import type { Job } from "../types";

const STAGE_LABEL: Record<string, string> = {
  queued: "Queued",
  extracting: "Extracting page text",
  ocr: "Running OCR on scanned pages",
  deduplicating: "Detecting duplicate pages",
  tagging: "Tagging document type, provider, and date",
  embedding: "Indexing pages for search",
  mapping: "Summarizing documents (map)",
  reducing: "Combining into case summary (reduce)",
  chronology: "Building timeline",
  conflicts: "Checking for conflicting evidence",
  retrieving: "Retrieving relevant pages",
  assessing: "Assessing listing criteria",
  relevance: "Checking citation relevance",
  extracting_evidence: "Inventorying evidence",
  drafting: "Drafting records request",
  signals: "Checking CAL list and conflicts",
  done: "Done",
};

const BARS: [string, string, string][] = [
  ["pages_extracted", "pages_total", "Pages extracted"],
  ["chunks_embedded", "chunks_total", "Chunks embedded"],
  ["batches_done", "batches_total", "Batches summarized"],
  ["listings_done", "listings_total", "Listings assessed"],
];
const COUNTS: [string, string][] = [
  ["ocr_pages", "OCR'd"], ["duplicates", "duplicates"], ["admin_pages", "administrative"], ["tagged_llm", "AI-tagged"],
  ["pages_in_scope", "pages in scope"], ["events", "timeline events"], ["conflicts", "conflicts"],
];

export default function JobProgress({ job, title }: { job: Job | null; title?: string }) {
  if (!job) return null;
  const c = job.counters || {};
  const err = job.status === "error";
  return (
    <div role="status" aria-live="polite" className={`mb-3 border-l-8 bg-white p-3 text-sm ${err ? "border-[#b50909]" : job.status === "done" ? "border-[#00a91c]" : "border-[#005ea2]"}`}>
      <p className="font-bold">
        {title ?? "Processing"}: {err ? "Failed" : STAGE_LABEL[job.stage] ?? job.stage}
        <span className="ml-2 font-normal text-gray-700">{job.seconds}s</span>
      </p>
      {err && <p className="text-[#8b0a03]">{job.message}</p>}
      {BARS.filter(([, d]) => c[d]).map(([n, d, label]) => (
        <div key={n} className="mt-1">
          <div className="flex justify-between text-xs"><span>{label}</span><span>{c[n] ?? 0} / {c[d]}</span></div>
          <div className="h-2 w-full rounded bg-gray-200" role="progressbar" aria-valuemin={0} aria-valuemax={c[d]} aria-valuenow={c[n] ?? 0} aria-label={label}>
            <div className="h-2 rounded bg-[#005ea2]" style={{ width: `${Math.min(100, ((c[n] ?? 0) / c[d]) * 100)}%` }} />
          </div>
        </div>
      ))}
      <p className="mt-1 text-xs text-gray-800">{COUNTS.filter(([k]) => c[k]).map(([k, l]) => `${c[k]} ${l}`).join(" · ")}</p>
    </div>
  );
}
