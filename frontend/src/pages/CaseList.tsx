import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Alert, Button, Spinner } from "../components/ui";
import type { Claim } from "../types";
import { DECISION_LABEL, QUEUE_LABEL } from "../labels";

type SynthCase = { case_id: string; title: string; claimant: string; documents: number; pages: number };


export default function CaseList() {
  const [claims, setClaims] = useState<Claim[] | null>(null);
  const [cases, setCases] = useState<SynthCase[]>([]);
  const [pick, setPick] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [dob, setDob] = useState("");
  const [onset, setOnset] = useState("");
  const [filed, setFiled] = useState("");
  const [files, setFiles] = useState<FileList | null>(null);
  const nav = useNavigate();

  const load = () => api.get<Claim[]>("/api/claims").then(setClaims).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    api.get<SynthCase[]>("/api/synthetic-cases").then((c) => { setCases(c); setPick(c[0]?.case_id ?? ""); }).catch(() => undefined);
  }, []);

  async function loadSynthetic() {
    setBusy(true); setErr(null);
    try {
      const c = await api.post<Claim>(`/api/synthetic-cases/${pick}/load`);
      nav(`/claims/${c.id}`);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  async function createWithUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!files?.length) { setErr("Choose at least one PDF."); return; }
    setBusy(true); setErr(null);
    try {
      const c = await api.post<Claim>("/api/claims", { claimant_name: name, dob: dob || null, alleged_onset_date: onset || null, filed_date: filed || null });
      await api.upload(`/api/claims/${c.id}/documents`, files);
      nav(`/claims/${c.id}`);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="mx-auto max-w-6xl p-6">
      <h1 className="mb-4 text-2xl font-bold">Case intake</h1>
      {err && <div className="mb-4"><Alert type="error" title="Something went wrong">{err}</Alert></div>}
      <div className="mb-8 grid gap-4 md:grid-cols-2">
        <section className="border border-gray-300 bg-white p-4" aria-labelledby="synth-h">
          <h2 id="synth-h" className="mb-2 text-lg font-bold">Load a synthetic claim file</h2>
          <p className="mb-3 text-sm text-gray-700">Fictional records generated for this prototype. Uploads go through the same extraction pipeline.</p>
          <label htmlFor="synth" className="mb-1 block text-sm font-bold">Synthetic case</label>
          <select id="synth" value={pick} onChange={(e) => setPick(e.target.value)} className="mb-3 w-full rounded border border-gray-600 bg-white px-2 py-2 text-sm">
            {cases.map((c) => <option key={c.case_id} value={c.case_id}>{c.claimant} — {c.title} ({c.pages} pages)</option>)}
          </select>
          <Button onClick={loadSynthetic} disabled={busy || !pick}>Load case</Button>
        </section>
        <form className="border border-gray-300 bg-white p-4" onSubmit={createWithUpload} aria-labelledby="up-h">
          <h2 id="up-h" className="mb-2 text-lg font-bold">New claim from PDFs</h2>
          <label htmlFor="cname" className="mb-1 block text-sm font-bold">Claimant name (synthetic only)</label>
          <input id="cname" required value={name} onChange={(e) => setName(e.target.value)} className="mb-3 w-full rounded border border-gray-600 px-2 py-2 text-sm" />
          <div className="mb-3 grid grid-cols-3 gap-2">
            <DateField id="dob" label="Date of birth" value={dob} onChange={setDob} />
            <DateField id="onset" label="Alleged onset" value={onset} onChange={setOnset} />
            <DateField id="filed" label="Filing date" value={filed} onChange={setFiled} />
          </div>
          {!filed && <p className="mb-2 text-xs text-gray-700">Without a filing date, evidence-recency checks are measured from today.</p>}
          <label htmlFor="files" className="mb-1 block text-sm font-bold">Medical record PDFs</label>
          <input id="files" type="file" accept="application/pdf" multiple onChange={(e) => setFiles(e.target.files)}
            className="mb-1 block w-full text-sm file:mr-3 file:rounded file:border-2 file:border-[#005ea2] file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-bold file:text-[#005ea2] hover:file:bg-blue-50" />
          <p className="mb-3 text-xs text-gray-700">{files?.length ? `${files.length} file(s) selected` : "Hold ⌘ (Mac) or Ctrl to select several files."} Scanned pages are OCR'd automatically.</p>
          <Button type="submit" disabled={busy}>Create claim and extract pages</Button>
        </form>
      </div>
      {busy && <Spinner label="Uploading…" />}
      <h2 className="mb-2 text-lg font-bold">Claims</h2>
      {!claims ? <Spinner label="Loading claims…" /> : claims.length === 0 ? <p className="text-sm">No claims yet. Load a synthetic case above.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse bg-white text-sm">
            <thead><tr className="border-b-2 border-gray-800 text-left">
              <th className="p-2">Claim #</th><th className="p-2">Claimant</th><th className="p-2">Filed</th><th className="p-2">Status</th>
              <th className="p-2">AI-suggested queue</th><th className="p-2">Assigned queue</th><th className="p-2">Examiner decision</th>
            </tr></thead>
            <tbody>
              {claims.map((c) => (
                <tr key={c.id} className="border-b border-gray-300 hover:bg-blue-50">
                  <td className="p-2"><Link className="font-semibold text-[#005ea2] underline" to={`/claims/${c.id}`}>{c.claim_number}</Link></td>
                  <td className="p-2">{c.claimant_name}</td>
                  <td className="p-2">{c.filed_date ?? "—"}</td>
                  <td className="p-2 capitalize">{c.status.replace("_", " ")}</td>
                  <td className="p-2">{c.ai_suggested_queue ? QUEUE_LABEL[c.ai_suggested_queue] : "—"}</td>
                  <td className="p-2">{c.final_queue ? QUEUE_LABEL[c.final_queue] : "—"}</td>
                  <td className="p-2">{c.decision ? DECISION_LABEL[c.decision] : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DateField({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-bold">{label}</label>
      <input id={id} type="date" value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded border border-gray-600 px-1 py-1 text-sm" />
    </div>
  );
}
