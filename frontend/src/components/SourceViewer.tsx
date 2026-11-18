import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { DocumentMeta, PageTags, SourceTarget } from "../types";

type PageResp = { doc_id: number; doc_label: string; page: number; page_count: number; text: string; tags?: PageTags };

export default function SourceViewer({ docs, target, onNavigate }: { docs: DocumentMeta[]; target: SourceTarget | null; onNavigate: (t: SourceTarget) => void }) {
  const [page, setPage] = useState<PageResp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const markRef = useRef<HTMLElement>(null);
  const t = target ?? (docs[0] ? { docId: docs[0].id, page: 1 } : null);

  const docId = t?.docId;
  const pageNo = t?.page;
  useEffect(() => {
    if (docId == null || pageNo == null) return;
    setErr(null);
    api.get<PageResp>(`/api/documents/${docId}/pages/${pageNo}`).then(setPage).catch((e) => setErr(String(e.message)));
  }, [docId, pageNo]);

  useEffect(() => {
    markRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [page, t?.start]);

  if (!t) return <p className="p-4 text-sm">No documents uploaded yet.</p>;
  const hasMark = page && t.start != null && t.end != null && page.doc_id === t.docId && page.page === t.page;

  return (
    <section aria-label="Source document viewer" className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-gray-300 bg-gray-100 px-3 py-2">
        <label className="text-xs font-bold" htmlFor="doc-select">Document</label>
        <select
          id="doc-select"
          className="max-w-[18rem] rounded border border-gray-500 bg-white px-2 py-1 text-sm"
          value={t.docId}
          onChange={(e) => onNavigate({ docId: Number(e.target.value), page: 1 })}
        >
          {docs.map((d) => (
            <option key={d.id} value={d.id}>{d.doc_label}{d.status === "processing" ? " (processing…)" : ` (${d.page_count} p.)`}</option>
          ))}
        </select>
        <div className="flex items-center gap-1">
          <button className="rounded border border-gray-500 bg-white px-2 py-1 text-sm disabled:opacity-40" disabled={t.page <= 1} onClick={() => onNavigate({ docId: t.docId, page: t.page - 1 })} aria-label="Previous page">‹</button>
          <span className="text-sm" aria-live="polite">Page {t.page} of {page?.page_count ?? "…"}</span>
          <button className="rounded border border-gray-500 bg-white px-2 py-1 text-sm disabled:opacity-40" disabled={!page || t.page >= page.page_count} onClick={() => onNavigate({ docId: t.docId, page: t.page + 1 })} aria-label="Next page">›</button>
        </div>
        <a className="ml-auto text-sm font-semibold text-[#005ea2] underline" href={`/api/documents/${t.docId}/file#page=${t.page}`} target="_blank" rel="noreferrer">
          Open original PDF page ↗
        </a>
      </div>
      {t.quote && (
        <p className={`px-3 py-1 text-xs ${hasMark ? "bg-yellow-50 text-gray-800" : "bg-red-50 font-semibold text-[#8b0a03]"}`}>
          {hasMark ? "Highlighted: text matched by the citation verifier." : "This quote could not be found on this page. Treat the related AI statement as unverified."}
        </p>
      )}
      {page?.tags && <TagBar tags={page.tags} onNavigate={onNavigate} />}
      {err && <p className="p-3 text-sm text-[#b50909]">{err}</p>}
      <div className="flex-1 overflow-auto bg-white p-4">
        <p className="mb-2 text-xs uppercase tracking-wide text-gray-600">Extracted page text (system of record for citations)</p>
        <pre className="whitespace-pre-wrap font-mono text-[13px] leading-relaxed text-gray-900">
          {page && hasMark ? (
            <>
              {page.text.slice(0, t.start!)}
              <mark ref={markRef} className="bg-yellow-300 outline outline-2 outline-yellow-600">{page.text.slice(t.start!, t.end!)}</mark>
              {page.text.slice(t.end!)}
            </>
          ) : (
            page?.text
          )}
        </pre>
      </div>
    </section>
  );
}

function TagBar({ tags, onNavigate }: { tags: PageTags; onNavigate: (t: SourceTarget) => void }) {
  const chip = "rounded border px-1.5 py-0.5 text-xs";
  return (
    <div className="flex flex-wrap items-center gap-1.5 border-b border-gray-300 bg-white px-3 py-1.5">
      {tags.doc_type && <span className={`${chip} border-gray-500`}>{tags.doc_type.replace(/_/g, " ")}{tags.tag_source === "llm" ? " (AI-tagged)" : ""}</span>}
      {tags.service_date && <span className={`${chip} border-gray-500`}>DOS {tags.service_date}</span>}
      {tags.provider && <span className={`${chip} border-gray-500`}>{tags.provider}</span>}
      {tags.is_admin && <span className={`${chip} border-gray-400 bg-gray-100`}>administrative (excluded from AI analysis)</span>}
      {tags.ocr && <span className={`${chip} border-[#c2850c] bg-[#faf3d1] font-semibold`}>OCR text · confidence {tags.ocr_confidence?.toFixed(0)}%</span>}
      {tags.duplicate_of && (
        <button className={`${chip} border-[#005ea2] bg-blue-50 font-semibold text-[#1a4480] underline`} onClick={() => onNavigate({ docId: tags.duplicate_of!.doc_id, page: tags.duplicate_of!.page })}>
          {tags.duplicate_of.kind} duplicate of {tags.duplicate_of.doc_label} p. {tags.duplicate_of.page}
        </button>
      )}
    </div>
  );
}
