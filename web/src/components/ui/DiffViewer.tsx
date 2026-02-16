interface DiffViewerProps {
  diff: string;
}

export default function DiffViewer({ diff }: DiffViewerProps) {
  const lines = diff.split("\n");
  return (
    <div className="max-h-[36rem] overflow-auto rounded border border-ink/20 bg-[#0e1726] p-3 font-mono text-xs">
      {lines.map((line, idx) => {
        let cls = "text-slate-200";
        if (line.startsWith("+++") || line.startsWith("---")) cls = "text-cyan-300";
        else if (line.startsWith("@@")) cls = "text-amber-300";
        else if (line.startsWith("+")) cls = "text-green-300";
        else if (line.startsWith("-")) cls = "text-rose-300";
        else if (line.startsWith("diff --git")) cls = "text-violet-300";
        return (
          <div key={`${idx}:${line.slice(0, 8)}`} className={`${cls} whitespace-pre-wrap`}>
            {line || " "}
          </div>
        );
      })}
    </div>
  );
}
