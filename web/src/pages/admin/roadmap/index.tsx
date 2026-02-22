import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Search, Map, Plus } from "lucide-react";
import Header from "../../../components/layout/Header";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import Badge from "../../../components/ui/Badge";
import Input from "../../../components/ui/Input";
import { listFeatureRequests, updateBug } from "../../../api/endpoints";

export default function AdminRoadmapPage() {
    const [search, setSearch] = useState("");
    const { data, refetch } = useQuery({ queryKey: ["roadmap-items"], queryFn: listFeatureRequests });

    const updateStatusMutation = useMutation({
        mutationFn: ({ id, status }: { id: string; status: string }) => updateBug(id, { status }),
        onSuccess: () => refetch(),
    });

    const columns = [
        { key: "open", label: "Open Backlog", bg: "bg-surface" },
        { key: "in_progress", label: "In Progress", bg: "bg-blue-50 dark:bg-blue-900/10" },
        { key: "resolved", label: "Resolved", bg: "bg-emerald-50 dark:bg-emerald-900/10" },
        { key: "closed", label: "Closed", bg: "bg-surface" },
    ];

    const items = data?.items || [];

    return (
        <div className="space-y-6 h-full flex flex-col min-h-screen">
            <div className="flex items-center justify-between">
                <Header title="Feature Roadmap" subtitle="Kanban board reflecting system feature requests" icon={<Map className="h-6 w-6" />} />
                <Button variant="primary" icon={<Plus className="h-4 w-4" />}>
                    New Feature Request
                </Button>
            </div>

            <div className="flex gap-4">
                <div className="flex-1">
                    <Input
                        placeholder="Search features..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                    />
                </div>
            </div>

            <div className="flex-1 flex gap-4 overflow-x-auto pb-4">
                {columns.map(col => {
                    const colItems = items.filter(item => item.status === col.key && (search === "" || item.title.toLowerCase().includes(search.toLowerCase())));
                    return (
                        <div key={col.key} className={`flex-1 min-w-[300px] rounded-xl flex flex-col border border-[var(--border-default)] ${col.bg}`}>
                            <div className="p-3 border-b border-[var(--border-default)] flex justify-between items-center font-semibold text-sm">
                                <span>{col.label}</span>
                                <Badge variant="default">{colItems.length}</Badge>
                            </div>
                            <div className="p-3 flex-1 overflow-y-auto space-y-3">
                                {colItems.map(item => (
                                    <Card key={item.id} className="cursor-pointer hover:-translate-y-1 transition-transform">
                                        <div className="text-sm font-semibold mb-2 text-[var(--text-primary)]">{item.title}</div>
                                        <div className="flex justify-between items-center text-xs">
                                            <Badge variant={item.priority === 'critical' || item.priority === 'high' ? 'danger' : 'info'}>
                                                {item.priority}
                                            </Badge>
                                            <span className="text-[var(--text-muted)] font-mono">{item.id.slice(0, 8)}</span>
                                        </div>
                                    </Card>
                                ))}
                                {colItems.length === 0 && (
                                    <div className="text-center p-4 text-xs text-[var(--text-muted)] border-2 border-dashed border-[var(--border-strong)] rounded-lg">
                                        No features {col.label.toLowerCase()}
                                    </div>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
