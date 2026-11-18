const MAP: Record<string, [string, string]> = {
  // criterion level
  met: ["Met", "bg-[#00a91c] text-white border-[#008817]"],
  not_met: ["Not met", "bg-gray-100 text-gray-900 border-gray-500"],
  insufficient_evidence: ["Insufficient evidence", "bg-[#ffbe2e] text-gray-900 border-[#c2850c]"],
  not_documented: ["Not documented", "bg-white text-gray-800 border-gray-500 border-dashed"],
  unverified: ["Insufficient evidence (citation unverified)", "bg-red-50 text-[#8b0a03] border-[#b50909]"],
  unsupported: ["Insufficient evidence (citation not relevant)", "bg-[#faf3d1] text-gray-900 border-[#c2850c]"],
  not_assessed: ["Not assessed", "bg-gray-100 text-gray-800 border-gray-500"],
  // listing level: refers to THAT listing only; "not met" is neutral gray, never alarming red
  criteria_appear_met: ["Listing appears met", "bg-[#00a91c] text-white border-[#008817]"],
  criteria_not_met: ["Listing not met", "bg-gray-100 text-gray-800 border-gray-400"],
};

export const STATUS_LABEL = (s: string) => (MAP[s] ?? [s])[0];

export default function StatusBadge({ status, listing = false }: { status: string; listing?: boolean }) {
  const key = listing && status === "insufficient_evidence" ? "insufficient_evidence" : status;
  const [label, cls] = MAP[key] ?? [status, "bg-gray-100 border-gray-500"];
  return <span className={`inline-block whitespace-nowrap rounded border-2 px-1.5 py-0.5 text-xs font-bold ${cls}`}>{label}</span>;
}
