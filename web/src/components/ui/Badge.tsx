import type { PropsWithChildren } from "react";

type Variant = "default" | "success" | "warning" | "danger" | "info";

const variantClasses: Record<Variant, string> = {
  default: "bg-ink/10 text-ink",
  success: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  warning: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  danger: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  info: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
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
