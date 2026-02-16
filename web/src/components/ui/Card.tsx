import type { PropsWithChildren, ReactNode } from "react";

interface CardProps {
  header?: ReactNode;
  footer?: ReactNode;
  className?: string;
}

export default function Card({
  header,
  footer,
  className = "",
  children,
}: PropsWithChildren<CardProps>) {
  return (
    <div
      className={`rounded-xl border border-[var(--border-default)] bg-surface shadow-sm ${className}`}
    >
      {header ? (
        <div className="border-b border-[var(--border-default)] px-4 py-3">{header}</div>
      ) : null}
      <div className="px-4 py-3">{children}</div>
      {footer ? (
        <div className="border-t border-[var(--border-default)] px-4 py-3">{footer}</div>
      ) : null}
    </div>
  );
}
