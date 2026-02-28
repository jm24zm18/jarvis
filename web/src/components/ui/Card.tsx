import type { PropsWithChildren, ReactNode } from "react";
import { cn } from "../../lib/utils";

interface CardProps {
  header?: ReactNode;
  footer?: ReactNode;
  className?: string;
  noPadding?: boolean;
}

export default function Card({
  header,
  footer,
  className,
  noPadding = false,
  children,
}: PropsWithChildren<CardProps>) {
  return (
    <div
      className={cn(
        "rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] transition-colors",
        className,
      )}
    >
      {header ? (
        <div className="border-b border-[var(--color-border)] px-4 py-3 bg-transparent rounded-t-lg">
          {header}
        </div>
      ) : null}
      <div className={noPadding ? "" : "px-4 py-3"}>{children}</div>
      {footer ? (
        <div className="border-t border-[var(--color-border)] px-4 py-3 rounded-b-lg">
          {footer}
        </div>
      ) : null}
    </div>
  );
}
