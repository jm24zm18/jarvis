import type { PropsWithChildren, ReactNode } from "react";

interface CardProps {
  header?: ReactNode;
  footer?: ReactNode;
  className?: string;
  noPadding?: boolean;
}

export default function Card({
  header,
  footer,
  className = "",
  noPadding = false,
  children,
}: PropsWithChildren<CardProps>) {
  return (
    <div
      className={`rounded-xl border border-[var(--border-default)] bg-surface shadow-sm transition-all duration-200 hover:shadow-md ${className}`}
    >
      {header ? (
        <div className="border-b border-[var(--border-default)] px-4 py-3 bg-[var(--bg-mist)]/50 rounded-t-xl">{header}</div>
      ) : null}
      <div className={noPadding ? "" : "px-4 py-3"}>{children}</div>
      {footer ? (
        <div className="border-t border-[var(--border-default)] px-4 py-3 bg-[var(--bg-mist)]/30 rounded-b-xl">{footer}</div>
      ) : null}
    </div>
  );
}
