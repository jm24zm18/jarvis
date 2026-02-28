import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { GitBranch, Activity, GitCommit, RefreshCcw } from "lucide-react";
import Header from "../../../components/layout/Header";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import Badge from "../../../components/ui/Badge";
import Input from "../../../components/ui/Input";
import {
    repoStatus,
    repoLog,
    repoBranches,
    repoDiff,
    repoStage,
    repoUnstage,
    repoCommit,
} from "../../../api/endpoints";

export default function AdminRepoPage() {
    const [commitMessage, setCommitMessage] = useState("");
    const [selectedFile, setSelectedFile] = useState<string | null>(null);

    const status = useQuery({ queryKey: ["repo-status"], queryFn: repoStatus });
    const log = useQuery({ queryKey: ["repo-log"], queryFn: () => repoLog(10) });
    const branches = useQuery({ queryKey: ["repo-branches"], queryFn: repoBranches });

    const diff = useQuery({
        queryKey: ["repo-diff", selectedFile],
        queryFn: () => repoDiff("working", selectedFile ?? undefined),
        enabled: !!selectedFile,
    });

    const refreshAll = () => {
        status.refetch();
        log.refetch();
        branches.refetch();
        if (selectedFile) diff.refetch();
    };

    const stageMutation = useMutation({
        mutationFn: (paths: string[]) => repoStage({ paths }),
        onSuccess: refreshAll,
    });

    const unstageMutation = useMutation({
        mutationFn: (paths: string[]) => repoUnstage(paths),
        onSuccess: refreshAll,
    });

    const commitMutation = useMutation({
        mutationFn: () => repoCommit(commitMessage),
        onSuccess: () => {
            setCommitMessage("");
            refreshAll();
        },
    });

    const d = status.data;

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <Header title="Repository Ops" subtitle="Manage Jarvis workspace via local git interface" />
                <Button variant="secondary" icon={<RefreshCcw className={`h-4 w-4 ${status.isFetching ? 'animate-spin' : ''}`} />} onClick={refreshAll}>
                    Refresh
                </Button>
            </div>

            <div className="flex gap-4 items-center mb-6 overflow-x-auto">
                <Card noPadding className="min-w-[200px] flex-1 px-4 py-3 border-l-4 border-l-accent">
                    <div className="flex items-center gap-2 text-sm font-medium text-text3 mb-1">
                        <GitBranch className="h-4 w-4" /> Current Branch
                    </div>
                    <div className="text-xl font-mono">{d?.branch || "Unknown"}</div>
                </Card>

                <Card noPadding className="min-w-[200px] flex-1 px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-text3 mb-1">
                        <Activity className="h-4 w-4" /> Upstream
                    </div>
                    <div className="text-xl font-mono">{d?.upstream || "None"}</div>
                </Card>

                <Card noPadding className="min-w-[200px] flex-1 px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-text3 mb-1">
                        <GitCommit className="h-4 w-4" /> Sync Status
                    </div>
                    <div className="flex gap-2 items-center text-sm font-medium">
                        <Badge variant="success">Ahead: {d?.ahead ?? 0}</Badge>
                        <Badge variant="warning">Behind: {d?.behind ?? 0}</Badge>
                    </div>
                </Card>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="space-y-6 lg:col-span-1">
                    {/* Staged Changes */}
                    <Card header={<div className="font-mono text-xs font-semibold uppercase tracking-widest text-text2 flex justify-between"><span>Staged Changes</span> <Badge>{d?.staged.length || 0}</Badge></div>}>
                        {d?.staged.length === 0 ? (
                            <p className="text-sm text-text3">No staged changes</p>
                        ) : (
                            <ul className="space-y-1">
                                {d?.staged.map(f => (
                                    <li key={f} className="flex items-center justify-between text-sm py-1">
                                        <span className="font-mono text-xs text-text cursor-pointer hover:underline" onClick={() => setSelectedFile(f)}>{f}</span>
                                        <Button variant="ghost" size="sm" onClick={() => unstageMutation.mutate([f])}>Unstage</Button>
                                    </li>
                                ))}
                            </ul>
                        )}

                        <div className="mt-4 pt-4 border-t border-[var(--color-border)]">
                            <Input
                                placeholder="Commit message..."
                                value={commitMessage}
                                onChange={(e) => setCommitMessage(e.target.value)}
                                className="mb-2"
                            />
                            <Button
                                variant="primary"
                                className="w-full"
                                disabled={!d?.staged.length || !commitMessage || commitMutation.isPending}
                                onClick={() => commitMutation.mutate()}
                            >
                                Commit Changes
                            </Button>
                        </div>
                    </Card>

                    {/* Unstaged Changes */}
                    <Card header={<div className="font-mono text-xs font-semibold uppercase tracking-widest text-text2 flex justify-between"><span>Unstaged Changes</span> <Badge>{d?.unstaged.length || 0}</Badge></div>}>
                        {d?.unstaged.length === 0 ? (
                            <p className="text-sm text-text3">Working tree clean</p>
                        ) : (
                            <ul className="space-y-1">
                                {d?.unstaged.map(f => (
                                    <li key={f} className="flex items-center justify-between text-sm py-1">
                                        <span className="font-mono text-xs text-text cursor-pointer hover:underline" onClick={() => setSelectedFile(f)}>{f}</span>
                                        <Button variant="ghost" size="sm" onClick={() => stageMutation.mutate([f])}>Stage</Button>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </Card>

                    {/* Untracked Files */}
                    <Card header={<div className="font-mono text-xs font-semibold uppercase tracking-widest text-text2 flex justify-between"><span>Untracked Files</span> <Badge>{d?.untracked.length || 0}</Badge></div>}>
                        {d?.untracked.length === 0 ? (
                            <p className="text-sm text-text3">No untracked files</p>
                        ) : (
                            <ul className="space-y-1">
                                {d?.untracked.map(f => (
                                    <li key={f} className="flex items-center justify-between text-sm py-1">
                                        <span className="font-mono text-xs text-text cursor-pointer hover:underline" onClick={() => setSelectedFile(f)}>{f}</span>
                                        <Button variant="ghost" size="sm" onClick={() => stageMutation.mutate([f])}>Stage</Button>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </Card>
                </div>

                <div className="lg:col-span-2 space-y-6">
                    <Card header={<h3 className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">Diff Viewer {selectedFile ? `- ${selectedFile}` : ''}</h3>}>
                        <div className="min-h-[400px] max-h-[600px] overflow-auto bg-surface-2 rounded-lg p-4 font-mono text-xs">
                            {diff.isLoading ? (
                                <div className="flex items-center justify-center h-full text-text3">Loading diff...</div>
                            ) : diff.data ? (
                                <pre>{diff.data}</pre>
                            ) : (
                                <div className="flex items-center justify-center h-full text-text3">Select a file to view diff</div>
                            )}
                        </div>
                    </Card>
                </div>
            </div>
        </div>
    );
}
