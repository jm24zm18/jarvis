import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Shield, ToggleLeft, ToggleRight } from "lucide-react";
import { allowPermission, deletePermission, listPermissions } from "../../../api/endpoints";
import Header from "../../../components/layout/Header";
import Input from "../../../components/ui/Input";
import Button from "../../../components/ui/Button";
import Card from "../../../components/ui/Card";
import Badge from "../../../components/ui/Badge";

export default function AdminPermissionsPage() {
  const [principalId, setPrincipalId] = useState("");
  const [toolName, setToolName] = useState("");

  const permissions = useQuery({ queryKey: ["permissions"], queryFn: listPermissions });
  const allow = useMutation({
    mutationFn: ({ principalId, toolName }: { principalId: string; toolName: string }) =>
      allowPermission(principalId, toolName),
    onSuccess: () => void permissions.refetch(),
  });
  const remove = useMutation({
    mutationFn: ({ principalId, toolName }: { principalId: string; toolName: string }) =>
      deletePermission(principalId, toolName),
    onSuccess: () => void permissions.refetch(),
  });

  const toolUniverse = useMemo(() => {
    const set = new Set<string>();
    for (const group of permissions.data?.items ?? []) {
      for (const tool of Object.keys(group.tools ?? {})) set.add(tool);
    }
    return Array.from(set).sort();
  }, [permissions.data]);

  return (
    <div>
      <Header title="Permissions" subtitle="Matrix view + manual allow/remove operations" />

      {/* Edit permission form */}
      <Card
        className="mb-6"
        header={
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-[var(--text-muted)]" />
            <h3 className="font-display text-base text-[var(--text-primary)]">Edit Permission</h3>
          </div>
        }
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Input
            label="Principal ID"
            value={principalId}
            onChange={(e) => setPrincipalId(e.target.value)}
            placeholder="e.g. agent:planner"
          />
          <Input
            label="Tool Name"
            value={toolName}
            onChange={(e) => setToolName(e.target.value)}
            placeholder="e.g. web_search"
          />
          <div className="flex items-end">
            <Button
              variant="primary"
              icon={<ToggleRight className="h-4 w-4" />}
              className="w-full"
              onClick={() => allow.mutate({ principalId, toolName })}
              disabled={allow.isPending || !principalId || !toolName}
            >
              Allow
            </Button>
          </div>
          <div className="flex items-end">
            <Button
              variant="danger"
              icon={<ToggleLeft className="h-4 w-4" />}
              className="w-full"
              onClick={() => remove.mutate({ principalId, toolName })}
              disabled={remove.isPending || !principalId || !toolName}
            >
              Remove
            </Button>
          </div>
        </div>
      </Card>

      {/* Permission matrix */}
      <Card
        header={
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Shield className="h-4 w-4 text-[var(--text-muted)]" />
              <h3 className="font-display text-base text-[var(--text-primary)]">
                Permission Matrix
              </h3>
            </div>
            <Badge variant="default">
              {permissions.data?.items?.length ?? 0} principals / {toolUniverse.length} tools
            </Badge>
          </div>
        }
      >
        {toolUniverse.length === 0 ? (
          <div className="flex min-h-[120px] items-center justify-center">
            <p className="text-sm text-[var(--text-muted)]">
              No permissions configured yet.
            </p>
          </div>
        ) : (
          <div className="-mx-4 overflow-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--border-default)]">
                  <th className="sticky left-0 bg-surface px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                    Principal
                  </th>
                  {toolUniverse.map((tool) => (
                    <th
                      key={tool}
                      className="px-3 py-2.5 text-center text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]"
                    >
                      <div className="max-w-[100px] truncate" title={tool}>
                        {tool}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(permissions.data?.items ?? []).map((group) => (
                  <tr
                    key={group.principal_id}
                    className="border-b border-[var(--border-default)] transition hover:bg-[var(--bg-mist)]"
                  >
                    <td className="sticky left-0 bg-surface px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <Shield className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                        <div>
                          <div className="font-medium text-[var(--text-primary)]">
                            {group.principal_id}
                          </div>
                          <div className="text-[11px] text-[var(--text-muted)]">
                            {group.principal_type}
                          </div>
                        </div>
                      </div>
                    </td>
                    {toolUniverse.map((tool) => {
                      const allowed = group.tools?.[tool] === "allow";
                      return (
                        <td
                          key={`${group.principal_id}-${tool}`}
                          className="px-3 py-2.5 text-center"
                        >
                          <button
                            onClick={() =>
                              (allowed ? remove : allow).mutate({
                                principalId: group.principal_id,
                                toolName: tool,
                              })
                            }
                            className="inline-flex items-center justify-center rounded-md p-1 transition hover:bg-[var(--bg-mist)]"
                            title={
                              allowed
                                ? `Revoke ${tool} from ${group.principal_id}`
                                : `Grant ${tool} to ${group.principal_id}`
                            }
                          >
                            {allowed ? (
                              <ToggleRight className="h-6 w-6 text-leaf" />
                            ) : (
                              <ToggleLeft className="h-6 w-6 text-[var(--text-muted)]" />
                            )}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
