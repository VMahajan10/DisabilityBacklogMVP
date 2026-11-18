import { useEffect, useState } from "react";
import { api } from "../api";
import CitationChip from "../components/CitationChip";
import { AdvisoryNote, Spinner } from "../components/ui";
import type { Chronology, Citation, Conflict, SourceTarget } from "../types";

const TYPE_LABEL: Record<string, string> = {
  diagnosis: "Diagnosis", imaging: "Imaging", surgery: "Surgery", procedure: "Procedure", assistive_device: "Assistive device",
  emergency_visit: "ER visit", hospitalization: "Hospitalization", medical_opinion: "Medical opinion", therapy: "Therapy",
  medication_change: "Medication", fall_or_injury: "Fall / injury", other: "Other",
};
const KEY_TYPES = ["diagnosis", "imaging", "surgery", "procedure", "assistive_device", "emergency_visit", "hospitalization", "medical_opinion", "fall_or_injury"];

export default function TimelinePanel({ claimId, onCite, refreshKey }: { claimId: number; onCite: (t: SourceTarget, c: Citation) => void; refreshKey: number }) {
  const [data, setData] = useState<Chronology | null | undefined>(undefined);
  const [types, setTypes] = useState<Set<string>>(new Set(KEY_TYPES));
  useEffect(() => { api.get<Chronology | null>(`/api/claims/${claimId}/chronology`).then(setData); }, [claimId, refreshKey]);
  if (data === undefined) return <Spinner label="Loading timeline…" />;
  if (data === null) return <AdvisoryNote>The timeline and conflict check are built with the evidence summary. Generate the summary first.</AdvisoryNote>;
  const present = Array.from(new Set(data.events.map((e) => e.event_type)));
  const shown = data.events.filter((e) => types.has(e.event_type));
  return (
    <div>
      <section aria-labelledby="conf-h" className="mb-5">
        <h3 id="conf-h" className="mb-1 border-b border-gray-400 text-base font-bold">Conflicting evidence ({data.conflicts.length})</h3>
        <p className="mb-2 text-xs text-gray-700">Where sources disagree, both sides are shown with their citations. The AI does not decide which is correct.</p>
        {data.conflicts.length === 0 ? <p className="text-sm">No conflicts between verified statements were found.</p> :
          data.conflicts.map((c, i) => <ConflictCard key={i} c={c} onCite={onCite} />)}
      </section>
      <section aria-labelledby="tl-h">
        <h3 id="tl-h" className="mb-1 border-b border-gray-400 text-base font-bold">Timeline ({shown.length} of {data.events.length} events)</h3>
        <fieldset className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
          <legend className="sr-only">Event types to show</legend>
          {present.map((t) => (
            <label key={t} className="flex items-center gap-1">
              <input type="checkbox" checked={types.has(t)} onChange={() => { const n = new Set(types); if (n.has(t)) n.delete(t); else n.add(t); setTypes(n); }} />
              {TYPE_LABEL[t] ?? t}
            </label>
          ))}
        </fieldset>
        <ol className="relative border-l-2 border-gray-400 pl-4">
          {shown.map((e, i) => (
            <li key={i} className="mb-3">
              <span className="absolute -left-[7px] mt-1.5 h-3 w-3 rounded-full border-2 border-white bg-[#005ea2]" aria-hidden />
              <p className="text-sm"><b>{e.date ?? "Undated"}</b> <span className="ml-1 rounded border border-gray-500 px-1 text-xs">{TYPE_LABEL[e.event_type] ?? e.event_type}</span></p>
              <p className="text-sm">{e.description}</p>
              {e.citations.slice(0, 3).map((c) => <CitationChip key={c.id} c={c} onOpen={onCite} />)}
              {e.citations.length > 3 && <p className="text-xs text-gray-700">+{e.citations.length - 3} more sources reporting the same event</p>}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function ConflictCard({ c, onCite }: { c: Conflict; onCite: (t: SourceTarget, c: Citation) => void }) {
  const [all, setAll] = useState(false);
  const N = 3;
  const side = (label: string, s: Conflict["side_a"]) => (
    <div className="flex-1 border border-gray-300 bg-white p-2">
      <p className="text-xs font-bold uppercase text-gray-700">{label}</p>
      <p className="text-sm font-semibold">{s.summary}</p>
      <ul className="text-xs text-gray-800">{(all ? s.statements : s.statements.slice(0, N)).map((st, i) => <li key={i}>{st.date ?? "undated"} · {st.source}: {st.text}</li>)}</ul>
      {(all ? s.citations : s.citations.slice(0, N)).map((x) => <CitationChip key={x.id} c={x} onOpen={onCite} />)}
      {!all && (s.statements.length > N || s.citations.length > N) && (
        <button className="mt-1 text-xs font-semibold text-[#005ea2] underline" onClick={() => setAll(true)}>
          Show all {Math.max(s.statements.length, s.citations.length)} supporting records
        </button>
      )}
    </div>
  );
  return (
    <div className="mb-3 border-l-8 border-[#c2850c] bg-[#faf3d1] p-2">
      <p className="text-sm font-bold">⚠ {c.topic}: <span className="font-normal">{c.description}</span></p>
      <div className="mt-2 flex flex-col gap-2 md:flex-row">{side("One source", c.side_a)}{side("Conflicting source", c.side_b)}</div>
    </div>
  );
}
