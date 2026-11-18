import { useEffect, useState } from "react";
import { api } from "../api";
import { Alert, Spinner } from "../components/ui";

type Src = { source_url: string; retrieved_at: string; retrieval_method: string; sha256: string } | null;
type Resp = { source: Src; chunk_count: number; listings: { code: string; title: string; text: string; criteria: { criterion_id: string; level: string; text: string }[] }[] };
type Cal = { source: Src; conditions: { name: string; poms_url: string }[] };

export default function ListingsReference() {
  const [data, setData] = useState<Resp | null>(null);
  const [cal, setCal] = useState<Cal | null>(null);
  const [q, setQ] = useState("");
  useEffect(() => {
    api.get<Resp>("/api/listings").then(setData);
    api.get<Cal>("/api/cal-conditions").then(setCal);
  }, []);
  if (!data) return <div className="p-6"><Spinner label="Loading reference data…" /></div>;
  return (
    <div className="mx-auto max-w-5xl p-6">
      <h1 className="mb-2 text-2xl font-bold">Reference data</h1>
      <p className="mb-4 text-sm">The listing match and CAL check only use the text below, which comes from SSA's website. Nothing is written from model memory.</p>
      {data.listings.length === 0 && <Alert type="warning" title="Listings not ingested">Run <code>make ingest</code>.</Alert>}
      <h2 className="mt-4 text-xl font-bold">Blue Book 1.00 Musculoskeletal Disorders – Adult (listings 1.15–1.23)</h2>
      <SourceLine s={data.source} extra={`${data.chunk_count} chunks indexed (listing, criterion, sub-criterion, 1.00 sections)`} />
      {data.listings.map((l) => (
        <details key={l.code} className="mb-2 border border-gray-300 bg-white">
          <summary className="cursor-pointer p-2 font-bold">{l.title}</summary>
          <pre className="whitespace-pre-wrap p-3 text-sm">{l.text}</pre>
          <p className="px-3 pb-2 text-xs text-gray-700">Chunks: {l.criteria.map((c) => c.criterion_id).join(", ")}</p>
        </details>
      ))}
      <h2 className="mt-8 text-xl font-bold">Compassionate Allowances conditions</h2>
      {cal && (
        <>
          <SourceLine s={cal.source} extra={`${cal.conditions.length} conditions`} />
          <label htmlFor="calq" className="text-sm font-bold">Filter</label>
          <input id="calq" value={q} onChange={(e) => setQ(e.target.value)} className="mb-2 ml-2 rounded border border-gray-600 px-2 py-1 text-sm" />
          <ul className="columns-1 text-sm md:columns-2">
            {cal.conditions.filter((c) => c.name.toLowerCase().includes(q.toLowerCase())).map((c) => (
              <li key={c.name}><a className="text-[#005ea2] underline" href={c.poms_url} target="_blank" rel="noreferrer">{c.name}</a></li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function SourceLine({ s, extra }: { s: Src; extra: string }) {
  if (!s) return null;
  return (
    <p className="mb-3 text-xs text-gray-700">
      Source: <a className="text-[#005ea2] underline" href={s.source_url} target="_blank" rel="noreferrer">{s.source_url}</a> · retrieved {new Date(s.retrieved_at).toLocaleString()} · {s.retrieval_method} · SHA-256 {s.sha256.slice(0, 12)}… · {extra}
    </p>
  );
}
