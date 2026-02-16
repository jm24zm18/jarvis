import Button from "./Button";

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}

export default function Pagination({ page, pageSize, total, onPage }: PaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const atStart = page <= 1;
  const atEnd = page >= pageCount;

  const pages: number[] = [];
  const start = Math.max(1, page - 2);
  const end = Math.min(pageCount, page + 2);
  for (let i = start; i <= end; i++) pages.push(i);

  return (
    <div className="mt-3 flex items-center justify-between text-xs text-[var(--text-muted)]">
      <span>
        Page {page} / {pageCount} ({total} items)
      </span>
      <div className="flex gap-1">
        <Button variant="ghost" size="sm" onClick={() => onPage(page - 1)} disabled={atStart}>
          Prev
        </Button>
        {pages.map((p) => (
          <Button
            key={p}
            variant={p === page ? "primary" : "ghost"}
            size="sm"
            onClick={() => onPage(p)}
          >
            {p}
          </Button>
        ))}
        <Button variant="ghost" size="sm" onClick={() => onPage(page + 1)} disabled={atEnd}>
          Next
        </Button>
      </div>
    </div>
  );
}
