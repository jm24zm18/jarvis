import type { ReactNode } from "react";

interface HeaderProps {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
}

export default function Header({ title, subtitle, icon }: HeaderProps) {
  return (
    <header className="mb-4 border-b border-[var(--border-default)] pb-3">
      <div className="flex items-center gap-2">
        {icon ? <span className="text-[var(--text-muted)]">{icon}</span> : null}
        <h2 className="font-display text-2xl text-[var(--text-primary)]">{title}</h2>
      </div>
      {subtitle ? <p className="mt-0.5 text-sm text-[var(--text-secondary)]">{subtitle}</p> : null}
    </header>
  );
}
