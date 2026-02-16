import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Server, CheckCircle, XCircle, Upload, ExternalLink } from "lucide-react";
import Header from "../../../components/layout/Header";
import Input from "../../../components/ui/Input";
import Button from "../../../components/ui/Button";
import Badge from "../../../components/ui/Badge";
import Card from "../../../components/ui/Card";
import {
  getGoogleOAuthConfig,
  getGoogleOAuthStatus,
  importGoogleOAuthFromLocal,
  startGoogleOAuth,
} from "../../../api/endpoints";

export default function AdminProvidersPage() {
  const configQuery = useQuery({
    queryKey: ["google-oauth-config"],
    queryFn: getGoogleOAuthConfig,
    refetchInterval: 10000,
  });

  const defaultRedirect = useMemo(() => {
    const proto = window.location.protocol;
    const host = window.location.hostname;
    return `${proto}//${host}:8000/api/v1/auth/google/callback`;
  }, []);

  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [redirectUri, setRedirectUri] = useState(defaultRedirect);
  const [running, setRunning] = useState(false);
  const [flowState, setFlowState] = useState("");
  const [status, setStatus] = useState("");
  const [detail, setDetail] = useState("");

  useEffect(() => {
    if (!flowState) return;
    const timer = window.setInterval(async () => {
      try {
        const item = await getGoogleOAuthStatus(flowState);
        setStatus(item.status);
        setDetail(item.detail);
        if (item.status === "success") {
          setRunning(false);
          setFlowState("");
          void configQuery.refetch();
        }
        if (item.status === "error" || item.status === "missing") {
          setRunning(false);
          setFlowState("");
        }
      } catch (err) {
        setStatus("error");
        setDetail(err instanceof Error ? err.message : "status poll failed");
        setRunning(false);
        setFlowState("");
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [configQuery, flowState]);

  const start = async () => {
    setRunning(true);
    setStatus("starting");
    setDetail("");
    try {
      const result = await startGoogleOAuth({
        client_id: clientId.trim() || undefined,
        client_secret: clientSecret.trim() || undefined,
        redirect_uri: redirectUri.trim() || undefined,
      });
      setFlowState(result.state);
      setStatus("pending");
      setDetail(`OAuth opened (client source: ${result.client_id_source}). Complete consent in the popup.`);
      window.open(result.auth_url, "_blank", "width=520,height=740");
    } catch (err) {
      setRunning(false);
      setStatus("error");
      setDetail(err instanceof Error ? err.message : "Failed to start OAuth flow");
    }
  };

  const importLocal = async () => {
    setRunning(true);
    setStatus("importing");
    setDetail("");
    try {
      const result = await importGoogleOAuthFromLocal();
      setStatus("success");
      setDetail(
        `Imported local Gemini CLI credentials for client ${result.client_id}. Auto-reload: API=${result.api_reloaded}, worker queue=${result.worker_reload_enqueued}.`,
      );
      void configQuery.refetch();
    } catch (err) {
      setStatus("error");
      setDetail(err instanceof Error ? err.message : "Failed to import local credentials");
    } finally {
      setRunning(false);
    }
  };

  const statusVariant = status === "success" ? "success" : status === "error" ? "danger" : status === "pending" || status === "importing" ? "warning" : "info";

  return (
    <div>
      <Header
        title="Providers"
        subtitle="Google Gemini OAuth onboarding and connection management"
        icon={<Server className="h-6 w-6" />}
      />

      {/* Connection Status */}
      <Card
        className="mb-6"
        header={
          <div className="flex items-center gap-2">
            <Server className="h-4 w-4 text-[var(--text-muted)]" />
            <span className="font-display text-sm font-semibold text-[var(--text-primary)]">
              Connection Status
            </span>
          </div>
        }
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex items-center gap-3 rounded-lg border border-[var(--border-default)] bg-[var(--bg-mist)] px-4 py-3">
            {configQuery.data?.configured ? (
              <CheckCircle className="h-5 w-5 shrink-0 text-leaf" />
            ) : (
              <XCircle className="h-5 w-5 shrink-0 text-ember" />
            )}
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">Gemini OAuth</p>
              <Badge variant={configQuery.data?.configured ? "success" : "danger"}>
                {configQuery.data?.configured ? "Configured" : "Not Configured"}
              </Badge>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-lg border border-[var(--border-default)] bg-[var(--bg-mist)] px-4 py-3">
            {configQuery.data?.has_client_credentials ? (
              <CheckCircle className="h-5 w-5 shrink-0 text-leaf" />
            ) : (
              <XCircle className="h-5 w-5 shrink-0 text-ember" />
            )}
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">Client Credentials</p>
              <Badge variant={configQuery.data?.has_client_credentials ? "success" : "warning"}>
                {configQuery.data?.has_client_credentials ? "Present" : "Missing"}
              </Badge>
            </div>
          </div>
        </div>
      </Card>

      {/* OAuth Configuration Form */}
      <Card
        header={
          <div className="flex items-center gap-2">
            <ExternalLink className="h-4 w-4 text-[var(--text-muted)]" />
            <span className="font-display text-sm font-semibold text-[var(--text-primary)]">
              Google OAuth Setup
            </span>
          </div>
        }
      >
        <p className="mb-4 text-sm text-[var(--text-secondary)]">
          Leave client fields empty to auto-detect from installed Gemini CLI (same strategy OpenClaw uses).
        </p>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Input
            label="GOOGLE_OAUTH_CLIENT_ID (optional)"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            placeholder="123...apps.googleusercontent.com"
          />
          <Input
            label="GOOGLE_OAUTH_CLIENT_SECRET (optional)"
            type="password"
            value={clientSecret}
            onChange={(e) => setClientSecret(e.target.value)}
            placeholder="GOCSPX-..."
          />
        </div>

        <div className="mt-4">
          <Input
            label="Redirect URI"
            value={redirectUri}
            onChange={(e) => setRedirectUri(e.target.value)}
          />
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <Button
            icon={<ExternalLink className="h-4 w-4" />}
            onClick={start}
            disabled={running}
          >
            {running ? "Waiting for OAuth..." : "Start Google OAuth"}
          </Button>
          <Button
            variant="secondary"
            icon={<Upload className="h-4 w-4" />}
            onClick={importLocal}
            disabled={running}
          >
            Import From Local Gemini CLI
          </Button>
          <Button
            variant="ghost"
            icon={<Server className="h-4 w-4" />}
            onClick={() => void configQuery.refetch()}
          >
            Refresh
          </Button>
        </div>

        {/* Status Feedback */}
        {(status || detail) && (
          <div
            className={`mt-4 rounded-lg border px-4 py-3 ${
              status === "success"
                ? "border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-900/20"
                : status === "error"
                  ? "border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-900/20"
                  : "border-[var(--border-default)] bg-[var(--bg-mist)]"
            }`}
          >
            {status && (
              <div className="mb-1 flex items-center gap-2">
                {status === "success" ? (
                  <CheckCircle className="h-4 w-4 text-leaf" />
                ) : status === "error" ? (
                  <XCircle className="h-4 w-4 text-ember" />
                ) : (
                  <Server className="h-4 w-4 text-[var(--text-muted)]" />
                )}
                <Badge variant={statusVariant}>{status}</Badge>
              </div>
            )}
            {detail && (
              <p className="text-sm text-[var(--text-secondary)]">{detail}</p>
            )}
          </div>
        )}

        <p className="mt-4 text-xs text-[var(--text-muted)]">
          After success, restart API and worker so new <code className="rounded bg-[var(--bg-mist)] px-1">.env</code> values are loaded.
        </p>
      </Card>
    </div>
  );
}
