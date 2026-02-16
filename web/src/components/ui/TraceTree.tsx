import { useMemo, useState } from "react";
import type { EventItem } from "../../types";

interface TraceTreeProps {
  events: EventItem[];
}

interface Node {
  id: string;
  event: EventItem;
  children: Node[];
}

export default function TraceTree({ events }: TraceTreeProps) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const roots = useMemo(() => buildTree(events), [events]);

  if (!events.length) return <p className="text-sm text-[var(--text-muted)]">No trace events.</p>;

  return (
    <div className="space-y-1 text-xs">
      {roots.map((node) => (
        <TraceNode
          key={node.id}
          node={node}
          depth={0}
          collapsed={collapsed}
          onToggle={(id) => setCollapsed((s) => ({ ...s, [id]: !s[id] }))}
        />
      ))}
    </div>
  );
}

function TraceNode({
  node,
  depth,
  collapsed,
  onToggle,
}: {
  node: Node;
  depth: number;
  collapsed: Record<string, boolean>;
  onToggle: (id: string) => void;
}) {
  const isCollapsed = !!collapsed[node.id];
  const hasChildren = node.children.length > 0;

  return (
    <div>
      <div className="flex items-start gap-2" style={{ paddingLeft: `${depth * 14}px` }}>
        <button
          className="w-4 text-left text-[var(--text-muted)]"
          onClick={() => hasChildren && onToggle(node.id)}
          disabled={!hasChildren}
        >
          {hasChildren ? (isCollapsed ? "+" : "-") : "\u2022"}
        </button>
        <div className="flex-1 rounded-lg bg-mist px-2 py-1">
          <div className="font-semibold text-[var(--text-primary)]">
            {node.event.event_type}{" "}
            <span className="font-normal text-[var(--text-muted)]">{node.event.component}</span>
          </div>
          <div className="text-[11px] text-[var(--text-muted)]">
            span={node.event.span_id} parent={node.event.parent_span_id ?? "root"}
          </div>
        </div>
      </div>
      {!isCollapsed
        ? node.children.map((child) => (
            <TraceNode
              key={child.id}
              node={child}
              depth={depth + 1}
              collapsed={collapsed}
              onToggle={onToggle}
            />
          ))
        : null}
    </div>
  );
}

function buildTree(events: EventItem[]): Node[] {
  const bySpan = new Map<string, Node>();
  const roots: Node[] = [];

  for (const event of events) {
    const id = event.span_id || event.id;
    bySpan.set(id, { id, event, children: [] });
  }

  for (const node of bySpan.values()) {
    const parent = node.event.parent_span_id;
    if (parent && bySpan.has(parent)) {
      bySpan.get(parent)?.children.push(node);
    } else {
      roots.push(node);
    }
  }

  const sortNodes = (items: Node[]) => {
    items.sort((a, b) => a.event.created_at.localeCompare(b.event.created_at));
    for (const item of items) sortNodes(item.children);
  };
  sortNodes(roots);
  return roots;
}
