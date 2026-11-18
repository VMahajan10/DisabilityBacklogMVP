import { useEffect, useState } from "react";
import { api } from "../api";
import { Alert, Button } from "../components/ui";
import { DECISION_LABEL } from "../labels";

type Det = { decision: string; notes: string; created_at: string; examiner: string } | null;

export default function DecisionPanel({ claimId, onChange }: { claimId: number; onChange: () => void }) {
  const [current, setCurrent] = useState<Det>(null);
  const [decision, setDecision] = useState("");
  const [notes, setNotes] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  useEffect(() => { api.get<Det>(`/api/claims/${claimId}/determination`).then(setCurrent); }, [claimId]);

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setErr(null); setOk(null);
    try {
      await api.post(`/api/claims/${claimId}/determination`, { decision, notes, evidence_reviewed_confirmed: confirmed });
      setOk("Determination recorded in the audit trail.");
      setCurrent(await api.get<Det>(`/api/claims/${claimId}/determination`));
      setDecision(""); setNotes(""); setConfirmed(false); onChange();
    } catch (e) { setErr((e as Error).message); }
  }

  return (
    <div>
      <div className="mb-3 border-l-8 border-gray-800 bg-white p-3 text-sm">
        <p className="font-bold">This panel is for the examiner only.</p>
        <p>The AI does not fill in, suggest, or pre-select a determination. Review the cited source pages before recording your decision.</p>
      </div>
      {current && (
        <Alert type="info" title="Current determination">
          {DECISION_LABEL[current.decision]} · {current.examiner} · {new Date(current.created_at).toLocaleString()}
          {current.notes && <p className="mt-1 whitespace-pre-wrap">Notes: {current.notes}</p>}
        </Alert>
      )}
      <form onSubmit={submit} className="mt-3 border-2 border-gray-800 bg-white p-4">
        <fieldset>
          <legend className="text-base font-bold">Record examiner determination</legend>
          {(["allowed", "denied", "needs_development"] as const).map((d) => (
            <label key={d} className="mt-2 flex items-center gap-2 text-sm">
              <input type="radio" name="decision" value={d} checked={decision === d} onChange={() => setDecision(d)} required />
              {DECISION_LABEL[d]}
            </label>
          ))}
        </fieldset>
        <label htmlFor="notes" className="mt-3 block text-sm font-bold">Examiner notes</label>
        <textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={5} className="w-full rounded border border-gray-600 p-2 text-sm" />
        <label className="mt-3 flex items-start gap-2 text-sm">
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-1 h-4 w-4" />
          <span><b>I reviewed the cited evidence</b> in the source documents and this determination is my own.</span>
        </label>
        <Button type="submit" className="mt-3" disabled={!decision || !confirmed}>Record determination</Button>
        {!confirmed && <p className="mt-1 text-xs text-gray-700">Tick the confirmation box to enable submission.</p>}
        {err && <div className="mt-2"><Alert type="error">{err}</Alert></div>}
        {ok && <p role="status" className="mt-2 text-sm text-[#00731d]">{ok}</p>}
      </form>
    </div>
  );
}
