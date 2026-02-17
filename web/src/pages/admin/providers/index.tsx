import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Server, CheckCircle, XCircle, ExternalLink } from "lucide-react";
import Header from "../../../components/layout/Header";
import Input from "../../../components/ui/Input";
import Button from "../../../components/ui/Button";
import Badge from "../../../components/ui/Badge";
import Card from "../../../components/ui/Card";
import {
  getProviderConfig,
  getProviderModelsCatalog,
  getGoogleOAuthConfig,
  getGoogleOAuthStatus,
  startGoogleOAuth,
  updateProviderConfig,
} from "../../../api/endpoints";

function formatQuotaBlockReason(reason: string): string {
  const text = reason.trim();
  if (!text) return "";
  const match = text.match(/\buntil\s+([0-9T:\-+.]+(?:Z|\+00:00))\s+UTC\b/i);
  if (!match) return text;

  const untilIso = match[1];
  const untilDate = new Date(untilIso);
  if (Number.isNaN(untilDate.getTime())) return text;

  const localUntil = new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  }).format(untilDate);

  return `Gemini quota exhausted. Primary provider paused until ${localUntil}.`;
}

export default function AdminProvidersPage() {
  const configQuery = useQuery({
    queryKey: ["google-oauth-config"],
    queryFn: getGoogleOAuthConfig,
    refetchInterval: 10000,
  });
  const providerQuery = useQuery({
    queryKey: ["provider-config"],
    queryFn: getProviderConfig,
  });
  const modelCatalogQuery = useQuery({
    queryKey: ["provider-models-catalog"],
    queryFn: getProviderModelsCatalog,
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
  const [primaryProvider, setPrimaryProvider] = useState<"gemini" | "sglang">("gemini");
  const [geminiModel, setGeminiModel] = useState("");
  const [sglangModel, setSglangModel] = useState("");
  const [savingProvider, setSavingProvider] = useState(false);
  const [providerStatus, setProviderStatus] = useState("");
  const [providerDetail, setProviderDetail] = useState("");
  const quotaDetail = useMemo(
    () => formatQuotaBlockReason(configQuery.data?.quota_block_reason ?? ""),
    [configQuery.data?.quota_block_reason],
  );
  const visibleGeminiModels = useMemo(() => {
    const verified = modelCatalogQuery.data?.gemini_verified_models ?? [];
    if (verified.length) {
      if (geminiModel && !verified.includes(geminiModel)) {
        return [geminiModel, ...verified];
      }
      return verified;
    }
    const all = modelCatalogQuery.data?.gemini_models ?? [];
    if (all.length) {
      if (geminiModel && !all.includes(geminiModel)) {
        return [geminiModel, ...all];
      }
      return all;
    }
    return [geminiModel || "gemini-2.5-flash"];
  }, [geminiModel, modelCatalogQuery.data]);

  useEffect(() => {
    if (!providerQuery.data) return;
    const nextPrimary = providerQuery.data.primary_provider === "sglang" ? "sglang" : "gemini";
    setPrimaryProvider(nextPrimary);
    setGeminiModel(providerQuery.data.gemini_model);
    setSglangModel(providerQuery.data.sglang_model);
  }, [providerQuery.data]);

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

  const saveProviderConfig = async () => {
    setSavingProvider(true);
    setProviderStatus("saving");
    setProviderDetail("");
    try {
      const result = await updateProviderConfig({
        primary_provider: primaryProvider,
        gemini_model: geminiModel.trim(),
        sglang_model: sglangModel.trim(),
      });
      setProviderStatus("success");
      setProviderDetail(
        `Saved provider config (primary=${result.primary_provider}, Gemini=${result.gemini_model}, SGLang=${result.sglang_model}). Auto-reload: API=${result.api_reloaded}, worker queue=${result.worker_reload_enqueued}.`,
      );
      void providerQuery.refetch();
    } catch (err) {
      setProviderStatus("error");
      setProviderDetail(err instanceof Error ? err.message : "Failed to save provider settings");
    } finally {
      setSavingProvider(false);
    }
  };

  const statusVariant = status === "success" ? "success" : status === "error" ? "danger" : status === "pending" ? "warning" : "info";

  return (
    <div>
      <Header
        title="Providers"
        subtitle="Provider routing, model selection, and Gemini OAuth onboarding"
        icon={<Server className="h-6 w-6" />}
      />

      <Card
        className="mb-6"
        header={
          <div className="flex items-center gap-2">
            <Server className="h-4 w-4 text-[var(--text-muted)]" />
            <span className="font-display text-sm font-semibold text-[var(--text-primary)]">
              Model Routing
            </span>
          </div>
        }
      >
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <label className="text-sm">
            <span className="mb-1 block font-medium text-[var(--text-primary)]">Primary Provider</span>
            <select
              className="w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-elevated)] px-3 py-2 text-sm text-[var(--text-primary)]"
              value={primaryProvider}
              onChange={(e) => setPrimaryProvider(e.target.value === "sglang" ? "sglang" : "gemini")}
            >
              <option value="gemini">Gemini (Code Assist)</option>
              <option value="sglang">SGLang (local)</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium text-[var(--text-primary)]">Gemini Model</span>
            <select
              className="w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-elevated)] px-3 py-2 text-sm text-[var(--text-primary)]"
              value={geminiModel}
              onChange={(e) => setGeminiModel(e.target.value)}
            >
              {visibleGeminiModels.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-xs text-[var(--text-muted)]">
              Source: {modelCatalogQuery.data?.gemini_source || "configured value"}{" "}
              {modelCatalogQuery.data?.gemini_verified_models.length
                ? "(verified for current OAuth account)"
                : "(unverified fallback list)"}
            </span>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium text-[var(--text-primary)]">SGLang Model</span>
            <select
              className="w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-elevated)] px-3 py-2 text-sm text-[var(--text-primary)]"
              value={sglangModel}
              onChange={(e) => setSglangModel(e.target.value)}
            >
              {(modelCatalogQuery.data?.sglang_models.length
                ? modelCatalogQuery.data.sglang_models
                : [sglangModel || "openai/gpt-oss-120b"]
              ).map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-xs text-[var(--text-muted)]">
              Source: {modelCatalogQuery.data?.sglang_source || "configured value"}
            </span>
          </label>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button onClick={saveProviderConfig} disabled={savingProvider}>
            {savingProvider ? "Saving..." : "Save Provider Settings"}
          </Button>
          <Button variant="ghost" onClick={() => void providerQuery.refetch()}>
            Refresh Provider Config
          </Button>
          <Button variant="ghost" onClick={() => void modelCatalogQuery.refetch()}>
            Refresh Model List
          </Button>
        </div>
        {(providerStatus || providerDetail) && (
          <div
            className={`mt-4 rounded-lg border px-4 py-3 ${
              providerStatus === "success"
                ? "border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-900/20"
                : providerStatus === "error"
                  ? "border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-900/20"
                  : "border-[var(--border-default)] bg-[var(--bg-mist)]"
            }`}
          >
            {providerStatus && (
              <div className="mb-1 flex items-center gap-2">
                <Badge
                  variant={
                    providerStatus === "success"
                      ? "success"
                      : providerStatus === "error"
                        ? "danger"
                        : "warning"
                  }
                >
                  {providerStatus}
                </Badge>
              </div>
            )}
            {providerDetail && (
              <p className="text-sm text-[var(--text-secondary)]">{providerDetail}</p>
            )}
          </div>
        )}
      </Card>

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
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
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
          <div className="flex items-center gap-3 rounded-lg border border-[var(--border-default)] bg-[var(--bg-mist)] px-4 py-3">
            {configQuery.data?.auto_refresh_enabled ? (
              <CheckCircle className="h-5 w-5 shrink-0 text-leaf" />
            ) : (
              <XCircle className="h-5 w-5 shrink-0 text-ember" />
            )}
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">Auto Refresh</p>
              <Badge variant={configQuery.data?.auto_refresh_enabled ? "success" : "warning"}>
                {configQuery.data?.auto_refresh_enabled ? "Enabled" : "Disabled"}
              </Badge>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-lg border border-[var(--border-default)] bg-[var(--bg-mist)] px-4 py-3">
            {configQuery.data?.quota_blocked ? (
              <XCircle className="h-5 w-5 shrink-0 text-ember" />
            ) : (
              <CheckCircle className="h-5 w-5 shrink-0 text-leaf" />
            )}
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">Quota Status</p>
              <Badge variant={configQuery.data?.quota_blocked ? "danger" : "success"}>
                {configQuery.data?.quota_blocked ? "Blocked" : "OK"}
              </Badge>
            </div>
          </div>
        </div>
        <div className="mt-3 space-y-1 text-xs text-[var(--text-muted)]">
          <p>
            Access token expires in:{" "}
            <strong className="text-[var(--text-secondary)]">
              {configQuery.data?.seconds_until_access_expiry ?? 0}s
            </strong>
          </p>
          <p>
            Tier:{" "}
            <strong className="text-[var(--text-secondary)]">
              {configQuery.data?.current_tier_name || configQuery.data?.current_tier_id || "unknown"}
            </strong>
          </p>
          {configQuery.data?.quota_blocked && quotaDetail ? (
            <p>
              Quota detail:{" "}
              <strong className="text-[var(--text-secondary)]">
                {quotaDetail}
              </strong>
            </p>
          ) : null}
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
