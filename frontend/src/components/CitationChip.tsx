import type { Citation, SourceTarget } from "../types";

/** Three states: verified + relevant (blue ✓), verified but not relevant (amber ⚠), unverified (red ✗). */
export default function CitationChip({ c, onOpen }: { c: Citation; onOpen: (t: SourceTarget, c: Citation) => void }) {
  const exists = c.doc_id && c.page;
  const label = exists ? `${c.doc_label}, p. ${c.page}` : "No valid source cited";
  const state = !c.verified ? "unverified" : c.relevant === false ? "not_relevant" : "ok";
  const style = {
    ok: "border-[#005ea2] bg-blue-50 text-[#1a4480]",
    not_relevant: "border-[#c2850c] bg-[#faf3d1] text-gray-900",
    unverified: "border-[#b50909] bg-red-50 text-[#8b0a03]",
  }[state];
  const icon = { ok: "✓", not_relevant: "⚠", unverified: "✗" }[state];
  const stateText = {
    ok: c.relevant ? "Verified and relevant" : "Verified",
    not_relevant: "Quote verified but may not support this claim",
    unverified: "Unverified",
  }[state];
  return (
    <span className="mt-1 block">
      <button
        type="button"
        disabled={!exists}
        onClick={() => exists && onOpen({ docId: c.doc_id!, page: c.page!, start: c.match_start, end: c.match_end, quote: c.quote }, c)}
        className={`rounded border px-2 py-0.5 text-left text-xs font-semibold underline-offset-2 hover:underline ${style}`}
        aria-label={`${stateText} citation: ${label}. Open source page.`}
        title={stateText}
      >
        {icon} {label}
      </button>
      {c.quote && <q className="ml-2 text-xs italic text-gray-700">{c.quote}</q>}
      {state === "unverified" && c.failure_reason && <span className="ml-2 text-xs font-semibold text-[#8b0a03]">({c.failure_reason})</span>}
      {state === "not_relevant" && (
        <span className="mt-0.5 block text-xs text-gray-900"><b>Warning:</b> quote found on the page, but it may not support this criterion. {c.relevance_reason}</span>
      )}
    </span>
  );
}
