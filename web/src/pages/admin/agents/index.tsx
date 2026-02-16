import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot, FileText, Key, Heart } from "lucide-react";
import { getAgent, listAgents } from "../../../api/endpoints";
import Header from "../../../components/layout/Header";
import Card from "../../../components/ui/Card";
import Badge from "../../../components/ui/Badge";

type DetailTab = "identity" | "soul" | "heartbeat" | "permissions";

export default function AdminAgentsPage() {
  const [selected, setSelected] = useState("");
  const [activeTab, setActiveTab] = useState<DetailTab>("identity");
  const agents = useQuery({ queryKey: ["agents"], queryFn: listAgents });
  const detail = useQuery({
    queryKey: ["agent", selected],
    queryFn: () => getAgent(selected),
    enabled: !!selected,
  });

  const tabs: { key: DetailTab; label: string; icon: typeof FileText }[] = [
    { key: "identity", label: "Identity", icon: FileText },
    { key: "soul", label: "Soul", icon: Heart },
    { key: "heartbeat", label: "Heartbeat", icon: Heart },
    { key: "permissions", label: "Permissions", icon: Key },
  ];

  const renderTabContent = () => {
    if (!detail.data) return null;

    switch (activeTab) {
      case "identity":
        return (
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-[var(--bg-mist)] p-4 text-xs leading-relaxed text-[var(--text-secondary)]">
            {detail.data.identity_md || "No identity document found."}
          </pre>
        );
      case "soul":
        return (
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-[var(--bg-mist)] p-4 text-xs leading-relaxed text-[var(--text-secondary)]">
            {detail.data.soul_md || "No soul document found."}
          </pre>
        );
      case "heartbeat":
        return (
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-[var(--bg-mist)] p-4 text-xs leading-relaxed text-[var(--text-secondary)]">
            {detail.data.heartbeat_md || "No heartbeat document found."}
          </pre>
        );
      case "permissions":
        return (
          <pre className="max-h-96 overflow-auto rounded-lg bg-[var(--bg-mist)] p-4 text-xs leading-relaxed text-[var(--text-secondary)]">
            {JSON.stringify(detail.data.permissions, null, 2)}
          </pre>
        );
      default:
        return null;
    }
  };

  return (
    <div>
      <Header title="Agents" subtitle="Bundle browser with permissions and markdown artifacts" />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[340px_1fr]">
        {/* Agent list */}
        <div className="space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-muted)]">
            Registry
          </h3>
          <div className="space-y-2">
            {(agents.data?.items ?? []).map((agent) => {
              const isActive = selected === agent.id;
              return (
                <button
                  key={agent.id}
                  onClick={() => {
                    setSelected(agent.id);
                    setActiveTab("identity");
                  }}
                  className={`w-full rounded-xl border p-3 text-left transition ${
                    isActive
                      ? "border-[var(--border-strong)] bg-surface shadow-sm"
                      : "border-[var(--border-default)] bg-transparent hover:border-[var(--border-strong)] hover:bg-surface"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div
                      className={`flex h-9 w-9 items-center justify-center rounded-lg ${
                        isActive
                          ? "bg-blue-100 dark:bg-blue-900/30"
                          : "bg-[var(--bg-mist)]"
                      }`}
                    >
                      <Bot
                        className={`h-4 w-4 ${
                          isActive
                            ? "text-blue-600 dark:text-blue-400"
                            : "text-[var(--text-muted)]"
                        }`}
                      />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-semibold text-[var(--text-primary)]">
                          {agent.id}
                        </span>
                        <Badge variant="info">{agent.tool_count} tools</Badge>
                      </div>
                      {agent.description ? (
                        <p className="mt-0.5 truncate text-xs text-[var(--text-muted)]">
                          {agent.description}
                        </p>
                      ) : null}
                    </div>
                  </div>
                </button>
              );
            })}
            {agents.isLoading ? (
              <p className="py-4 text-center text-sm text-[var(--text-muted)]">Loading agents...</p>
            ) : null}
            {!agents.isLoading && (agents.data?.items ?? []).length === 0 ? (
              <p className="py-4 text-center text-sm text-[var(--text-muted)]">
                No agents registered.
              </p>
            ) : null}
          </div>
        </div>

        {/* Detail panel */}
        <div>
          {!selected ? (
            <Card className="flex min-h-[300px] items-center justify-center">
              <div className="text-center">
                <Bot className="mx-auto mb-3 h-10 w-10 text-[var(--text-muted)]" />
                <p className="text-sm text-[var(--text-muted)]">
                  Select an agent from the registry to view details.
                </p>
              </div>
            </Card>
          ) : (
            <Card
              header={
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Bot className="h-5 w-5 text-[var(--text-secondary)]" />
                    <h3 className="font-display text-base text-[var(--text-primary)]">
                      {selected}
                    </h3>
                  </div>
                  {detail.isLoading ? (
                    <Badge variant="info">Loading...</Badge>
                  ) : (
                    <Badge variant="success">Loaded</Badge>
                  )}
                </div>
              }
            >
              {/* Tab navigation */}
              <div className="mb-4 flex gap-1 rounded-lg bg-[var(--bg-mist)] p-1">
                {tabs.map((tab) => {
                  const Icon = tab.icon;
                  const isTabActive = activeTab === tab.key;
                  return (
                    <button
                      key={tab.key}
                      onClick={() => setActiveTab(tab.key)}
                      className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium transition ${
                        isTabActive
                          ? "bg-surface text-[var(--text-primary)] shadow-sm"
                          : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                      }`}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      {tab.label}
                    </button>
                  );
                })}
              </div>

              {/* Tab content */}
              {detail.data ? (
                renderTabContent()
              ) : detail.isLoading ? (
                <div className="flex h-48 items-center justify-center">
                  <p className="text-sm text-[var(--text-muted)]">Loading agent data...</p>
                </div>
              ) : null}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
