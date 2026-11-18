import type { ReactNode } from "react";

export function Button({ children, variant = "primary", className = "", ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "outline" | "danger" }) {
  const v = {
    primary: "bg-[#005ea2] text-white hover:bg-[#1a4480] border-[#005ea2]",
    secondary: "bg-gray-800 text-white hover:bg-black border-gray-800",
    outline: "bg-white text-[#005ea2] border-[#005ea2] hover:bg-blue-50",
    danger: "bg-[#b50909] text-white hover:bg-[#8b0a03] border-[#b50909]",
  }[variant];
  return (
    <button
      className={`inline-flex items-center gap-2 rounded border-2 px-4 py-2 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-50 ${v} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Alert({ type = "info", title, children }: { type?: "info" | "error" | "warning" | "success"; title?: string; children?: ReactNode }) {
  const c = {
    info: "border-[#00bde3] bg-[#e7f6f8]",
    error: "border-[#b50909] bg-[#f4e3db]",
    warning: "border-[#ffbe2e] bg-[#faf3d1]",
    success: "border-[#00a91c] bg-[#ecf3ec]",
  }[type];
  return (
    <div role={type === "error" ? "alert" : "status"} className={`border-l-8 px-4 py-3 text-sm ${c}`}>
      {title && <p className="font-bold">{title}</p>}
      {children}
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <p role="status" className="flex items-center gap-2 text-sm text-gray-700">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#005ea2] border-t-transparent" aria-hidden />
      {label}
    </p>
  );
}

export function AdvisoryNote({ children }: { children: ReactNode }) {
  return <p className="mb-3 border border-gray-400 bg-gray-50 px-3 py-2 text-xs text-gray-800">{children}</p>;
}

export function RunInfo({ run }: { run: { model: string; provider: string; prompt: string; created_at: string; attempts: number } }) {
  return (
    <p className="mt-1 text-xs text-gray-600">
      Generated {new Date(run.created_at).toLocaleString()} · {run.provider}:{run.model} · prompt {run.prompt}
      {run.attempts > 1 ? ` · ${run.attempts} attempts` : ""}
    </p>
  );
}
