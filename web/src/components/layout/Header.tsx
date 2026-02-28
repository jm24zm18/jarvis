import type { ReactNode } from "react";

interface HeaderProps {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
}

export default function Header({ title, subtitle, icon }: HeaderProps) {
  return (
    <header className="mb-6">
      <div className="flex items-center gap-2">
        {icon ? <span className="text-accent">{icon}</span> : null}
        <h2 className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">
          {title}
        </h2>
      </div>
      {subtitle ? <p className="mt-1 text-sm text-text3">{subtitle}</p> : null}
    </header>
  );
}
