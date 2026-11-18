import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Job } from "./types";

/** Polls a job until it finishes; calls onDone once. */
export function useJob(jobId: number | null, onDone?: (j: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    if (jobId == null) return;
    let stop = false;
    const tick = async () => {
      try {
        const j = await api.get<Job>(`/api/jobs/${jobId}`);
        if (stop) return;
        setJob(j);
        if (j.status !== "running") { done.current?.(j); return; }
      } catch { /* keep polling */ }
      if (!stop) setTimeout(tick, 1000);
    };
    tick();
    return () => { stop = true; };
  }, [jobId]);
  return job;
}

