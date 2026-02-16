import type { ButtonHTMLAttributes, PropsWithChildren, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const variantClasses: Record<Variant, string> = {
  primary:
    "bg-[#13293d] text-white hover:bg-[#13293d]/90 dark:bg-slate-200 dark:text-slate-900 dark:hover:bg-slate-300",
  secondary:
    "bg-[var(--bg-mist)] text-[var(--text-primary)] hover:bg-[var(--border-strong)] border border-[var(--border-default)]",
  ghost:
    "bg-transparent text-[var(--text-primary)] hover:bg-[var(--bg-mist)]",
  danger:
    "bg-red-600 text-white hover:bg-red-700 dark:bg-red-700 dark:hover:bg-red-600",
};

const sizeClasses: Record<Size, string> = {
  sm: "px-2 py-1 text-xs",
  md: "px-3 py-2 text-sm",
  lg: "px-4 py-2.5 text-base",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
}

export default function Button({
  children,
  className = "",
  variant = "primary",
  size = "md",
  icon,
  ...props
}: PropsWithChildren<ButtonProps>) {
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-semibold transition disabled:opacity-60 ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
    >
      {icon}
      {children}
    </button>
  );
}
