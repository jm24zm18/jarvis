import type { PropsWithChildren } from "react";

type Variant = "default" | "success" | "warning" | "danger" | "info";

const variantClasses: Record<Variant, string> = {
  default: "bg-[var(--bg-mist)] text-[var(--text-primary)] border border-[var(--border-default)]",
  success: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  warning: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  danger: "bg-[var(--color-danger)]/20 text-[var(--color-danger)] dark:bg-[var(--color-danger)]/30 dark:text-red-300",
  info: "bg-[var(--color-brand)]/20 text-[var(--color-brand)] dark:bg-[var(--color-brand)]/30 dark:text-blue-300",
};

interface BadgeProps {
  variant?: Variant;
  className?: string;
}

export default function Badge({
  variant = "default",
  className = "",
  children,
}: PropsWithChildren<BadgeProps>) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${variantClasses[variant]} ${className}`}
    >
      {children}
    </span>
  );
}
