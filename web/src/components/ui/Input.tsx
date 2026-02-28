import type { InputHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}

export default function Input({ label, className, ...props }: InputProps) {
  const input = (
    <input
      {...props}
      className={cn(
        "w-full rounded-lg border border-[var(--color-border-2)] bg-[var(--color-surface)] px-3 py-2 text-sm font-mono text-text outline-none placeholder:text-text3 focus:border-accent focus:ring-1 focus:ring-accent-dim",
        className,
      )}
    />
  );
  if (!label) return input;
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-text2">{label}</span>
      {input}
    </label>
  );
}
