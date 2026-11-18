export type Claim = {
  id: number;
  claim_number: string;
  claimant_name: string;
  dob: string | null;
  alleged_onset_date: string | null;
  filed_date: string | null;
  status: string;
  created_at: string;
  decided_at: string | null;
  synthetic_case_id: string | null;
  ai_suggested_queue: string | null;
  final_queue: string | null;
  decision: string | null;
};

export type DocumentMeta = { id: number; filename: string; doc_label: string; page_count: number; status: string; sha256: string; uploaded_at: string };
export type ClaimDetail = Claim & { documents: DocumentMeta[]; ai_runs: string[]; page_count: number; processing: boolean };

export type Citation = {
  id: number;
  doc_id: number | null;
  doc_label: string;
  page: number | null;
  quote: string;
  verified: boolean;
  score: number;
  match_start: number | null;
  match_end: number | null;
  failure_reason: string | null;
  relevant?: boolean | null;
  relevance_reason?: string | null;
};

export type RunMeta = { id: number; kind: string; provider: string; model: string; prompt: string; created_at: string; attempts: number; latency_ms: number };
export type Verification = { citations: number; verified: number; unverified: number; rate: number | null };

export type Bullet = { text: string; verified: boolean; citations: Citation[] };
export type Summary = { run: RunMeta; sections: { key: string; title: string; bullets: Bullet[] }[]; verification: Verification;
  stats?: { map_batches: number; pages_in_scope: number; map_bullets_verified: number; events: number; statements: number } | null; map_model?: string | null };

export type SourceTarget = { docId: number; page: number; start?: number | null; end?: number | null; quote?: string };

export type AuditEvent = {
  id: number;
  timestamp: string;
  actor_type: "ai" | "human" | "system";
  actor: string;
  event_type: string;
  ai_run_id: number | null;
  payload: Record<string, unknown>;
};

export type CriterionRow = {
  criterion_id: string;
  level: "criterion" | "subcriterion";
  parent_id: string | null;
  criterion_text: string;
  body: string;
  ai_status: string | null;
  status: "met" | "not_met" | "insufficient_evidence" | "not_documented" | "unverified" | "unsupported" | "not_assessed";
  note: string | null;
  rationale: string;
  citations: Citation[];
};
export type ListingResult = {
  run_id: number;
  listing_code: string;
  title: string;
  name: string;
  listing_text: string;
  source_url: string;
  fetched_at: string;
  retrieval_score: number;
  ai_overall: string;
  overall: "criteria_appear_met" | "criteria_not_met" | "insufficient_evidence";
  overall_adjusted: boolean;
  overall_rationale: string;
  logic: "all" | "any";
  gate: { criterion_id: string; body: string; rationale: string } | null;
  criteria: CriterionRow[];
};
export type ListingMatch = {
  run: RunMeta;
  batch_id: string;
  listings: ListingResult[];
  banner: { any_met: boolean; met: { code: string; name: string }[]; others: string[] };
  verification: Verification & { relevant?: number; not_relevant?: number };
};

export type Flag = {
  type: string;
  explanation: string;
  suggested_action: string;
  source: "rule" | "ai" | "listing_match";
  provider_to_contact?: string | null;
  criteria?: string[];
  citations: Citation[];
};
export type MissingEvidence = {
  run: RunMeta;
  flags: Flag[];
  evidence_items: { category: string; date: string | null; source: string; description: string; includes_musculoskeletal_or_neuro_exam: boolean; verified: boolean; citations: Citation[] }[];
  thresholds: { imaging_recency_months: number; stale_record_months: number };
  letter: { id: number; draft_text: string; edited_text: string | null; updated_at: string } | null;
  verification: Verification;
};

export type Triage = {
  run: RunMeta;
  suggested_queue: "fast_track" | "standard" | "senior_examiner";
  reasons: string[];
  cal: { matched: boolean; cal_condition: string | null; reasoning: string; verified_match: string | null; citations: Citation[]; shortlist: string[] };
  conflicts: { description: string; verified: boolean; citations: Citation[] }[];
  complexity_notes: string[];
  top_listing: { code: string; overall: string } | null;
  assignment: { id: number; ai_suggested_queue: string; final_queue: string | null; overridden: boolean; override_reason: string | null; decided_at: string | null } | null;
  verification: Verification;
};

export type Job = {
  id: number;
  kind: string;
  status: "running" | "done" | "error";
  stage: string;
  counters: Record<string, number>;
  message: string | null;
  started_at: string;
  finished_at: string | null;
  seconds: number;
};
export type PageTags = {
  doc_type: string | null;
  provider: string | null;
  service_date: string | null;
  ocr: boolean;
  ocr_confidence: number | null;
  is_admin: boolean;
  tag_source: string | null;
  duplicate_of: { doc_id: number; page: number; kind: string; doc_label: string } | null;
};

export type TimelineEvent = { date: string | null; event_type: string; description: string; citations: Citation[] };
export type ConflictSideT = { summary: string; statements: { date: string | null; source: string; stance: string; text: string }[]; citations: Citation[] };
export type Conflict = { topic: string; description: string; side_a: ConflictSideT; side_b: ConflictSideT };
export type Chronology = { run: RunMeta; events: TimelineEvent[]; conflicts: Conflict[] };
