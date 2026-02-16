import type { InputHTMLAttributes } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}

export default function Input({ label, className, ...props }: InputProps) {
  const input = (
    <input
      {...props}
      className={`w-full rounded-lg border border-[var(--border-strong)] bg-surface px-3 py-2 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus:border-ember focus:ring-1 focus:ring-ember/30 ${className ?? ""}`}
    />
  );
  if (!label) return input;
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">{label}</span>
      {input}
    </label>
  );
}
