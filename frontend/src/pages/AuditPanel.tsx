import { useEffect, useState } from "react";
import { api } from "../api";
import { Spinner } from "../components/ui";
import type { AuditEvent } from "../types";

const ACTOR_STYLE = { ai: "bg-purple-100 text-purple-900 border-purple-700", human: "bg-green-100 text-green-900 border-green-700", system: "bg-gray-100 text-gray-900 border-gray-600" };

export default function AuditPanel({ claimId, refreshKey }: { claimId: number; refreshKey: number }) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { api.get<AuditEvent[]>(`/api/claims/${claimId}/audit`).then(setEvents); }, [claimId, refreshKey]);
  if (!events) return <Spinner label="Loading audit trail…" />;
  return (
    <div>
      <div className="mb-3 flex items-center gap-3">
        <a href={`/api/claims/${claimId}/audit/export`} className="rounded border-2 border-[#005ea2] bg-white px-4 py-2 text-sm font-bold text-[#005ea2] hover:bg-blue-50">
          Export audit trail (JSON)
        </a>
        <p className="text-xs text-gray-700">Every AI output (model, prompt version, citations, verification) and every examiner action.</p>
      </div>
      <ol className="space-y-2">
        {events.slice().reverse().map((e) => (
          <li key={e.id} className="border border-gray-300 bg-white p-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded border px-1.5 text-xs font-bold uppercase ${ACTOR_STYLE[e.actor_type]}`}>{e.actor_type}</span>
              <span className="font-semibold">{e.event_type.replace(/_/g, " ")}</span>
              <span className="text-xs text-gray-600">{e.actor}</span>
              <time className="ml-auto text-xs text-gray-600" dateTime={e.timestamp}>{new Date(e.timestamp).toLocaleString()}</time>
            </div>
            <AuditSummary e={e} />
            <button className="text-xs text-[#005ea2] underline" onClick={() => setOpen(open === e.id ? null : e.id)} aria-expanded={open === e.id}>
              {open === e.id ? "Hide" : "Show"} details
            </button>
            {open === e.id && <pre className="mt-1 max-h-72 overflow-auto bg-gray-50 p-2 text-xs">{JSON.stringify(e.payload, null, 2)}</pre>}
          </li>
        ))}
      </ol>
    </div>
  );
}

function AuditSummary({ e }: { e: AuditEvent }) {
  const p = e.payload as Record<string, unknown>;
  if (e.actor_type === "ai") {
    const v = (p.verification ?? {}) as { citations?: number; unverified?: number };
    return <p className="text-xs text-gray-800">Prompt {String(p.prompt)} · {String(p.model)} · {v.citations ?? 0} citations, {v.unverified ?? 0} unverified</p>;
  }
  if (e.event_type === "determination_recorded") return <p className="text-xs text-gray-800">Decision: <b>{String(p.decision)}</b>{p.notes ? ` · "${String(p.notes).slice(0, 120)}"` : ""}</p>;
  if (e.event_type.startsWith("triage_")) return <p className="text-xs text-gray-800">AI suggested {String(p.ai_suggested_queue)} → examiner assigned <b>{String(p.final_queue)}</b>{p.override_reason ? ` · reason: ${String(p.override_reason)}` : ""}</p>;
  if (e.event_type === "document_uploaded") return <p className="text-xs text-gray-800">{String(p.filename)} · {String(p.page_count)} pages · sha256 {String(p.sha256).slice(0, 12)}…</p>;
  if (e.event_type === "citation_viewed") return <p className="text-xs text-gray-800">Viewed {String(p.doc_label)} p. {String(p.page)}</p>;
  return null;
}
