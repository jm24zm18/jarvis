import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Server } from "lucide-react";
import Header from "../../../components/layout/Header";
import Input from "../../../components/ui/Input";
import Button from "../../../components/ui/Button";
import Badge from "../../../components/ui/Badge";
import Card from "../../../components/ui/Card";
import {
  getProviderConfig,
  getProviderModelsCatalog,
  updateProviderConfig,
} from "../../../api/endpoints";

export default function AdminProvidersPage() {
  const providerQuery = useQuery({
    queryKey: ["provider-config"],
    queryFn: getProviderConfig,
  });
  const modelCatalogQuery = useQuery({
    queryKey: ["provider-models-catalog"],
    queryFn: getProviderModelsCatalog,
  });

  const [primaryProvider, setPrimaryProvider] = useState<"openrouter" | "sglang">("openrouter");
  const [openrouterModel, setOpenrouterModel] = useState("");
  const [sglangModel, setSglangModel] = useState("");
  const [openrouterApiKey, setOpenrouterApiKey] = useState("");
  const [savingProvider, setSavingProvider] = useState(false);
  const [providerStatus, setProviderStatus] = useState("");
  const [providerDetail, setProviderDetail] = useState("");

  useEffect(() => {
    if (!providerQuery.data) return;
    const nextPrimary = providerQuery.data.primary_provider === "sglang" ? "sglang" : "openrouter";
    setPrimaryProvider(nextPrimary);
    setOpenrouterModel(providerQuery.data.openrouter_model);
    setSglangModel(providerQuery.data.sglang_model);
    setOpenrouterApiKey("");
  }, [providerQuery.data]);

  const saveProviderConfig = async () => {
    setSavingProvider(true);
    setProviderStatus("saving");
    setProviderDetail("");
    try {
      const payload: {
        primary_provider: "openrouter" | "sglang";
        openrouter_model: string;
        sglang_model: string;
        openrouter_api_key?: string;
      } = {
        primary_provider: primaryProvider,
        openrouter_model: openrouterModel.trim(),
        sglang_model: sglangModel.trim(),
      };
      const trimmedApiKey = openrouterApiKey.trim();
      if (trimmedApiKey) payload.openrouter_api_key = trimmedApiKey;
      const result = await updateProviderConfig({
        ...payload,
      });
      setProviderStatus("success");
      setProviderDetail(
        `Saved provider config (primary=${result.primary_provider}, OpenRouter=${result.openrouter_model}, SGLang=${result.sglang_model}, OpenRouter key=${result.openrouter_api_key_set ? "set" : "not set"}). Auto-reload: API=${result.api_reloaded}, worker queue=${result.worker_reload_enqueued}.`,
      );
      setOpenrouterApiKey("");
      void providerQuery.refetch();
    } catch (err) {
      setProviderStatus("error");
      setProviderDetail(err instanceof Error ? err.message : "Failed to save provider settings");
    } finally {
      setSavingProvider(false);
    }
  };

  const clearOpenrouterApiKey = async () => {
    setSavingProvider(true);
    setProviderStatus("saving");
    setProviderDetail("");
    try {
      const result = await updateProviderConfig({
        clear_openrouter_api_key: true,
      });
      setProviderStatus("success");
      setProviderDetail(
        `Cleared OpenRouter API key. Auto-reload: API=${result.api_reloaded}, worker queue=${result.worker_reload_enqueued}.`,
      );
      setOpenrouterApiKey("");
      void providerQuery.refetch();
    } catch (err) {
      setProviderStatus("error");
      setProviderDetail(err instanceof Error ? err.message : "Failed to clear OpenRouter API key");
    } finally {
      setSavingProvider(false);
    }
  };

  return (
    <div>
      <Header
        title="Providers"
        subtitle="Provider routing and model selection"
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
              onChange={(e) => setPrimaryProvider(e.target.value === "sglang" ? "sglang" : "openrouter")}
            >
              <option value="openrouter">OpenRouter</option>
              <option value="sglang">SGLang (local)</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium text-[var(--text-primary)]">OpenRouter Model</span>
            <Input
              value={openrouterModel}
              onChange={(e) => setOpenrouterModel(e.target.value)}
              placeholder="google/gemini-2.5-flash"
            />
            <span className="mt-1 block text-xs text-[var(--text-muted)]">
              Any model ID available on openrouter.ai
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
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
          <label className="text-sm md:col-span-2">
            <span className="mb-1 block font-medium text-[var(--text-primary)]">OpenRouter API Key</span>
            <Input
              type="password"
              value={openrouterApiKey}
              onChange={(e) => setOpenrouterApiKey(e.target.value)}
              placeholder="sk-or-v1-..."
            />
            <span className="mt-1 block text-xs text-[var(--text-muted)]">
              Current:{" "}
              {providerQuery.data?.openrouter_api_key_set
                ? providerQuery.data.openrouter_api_key_masked || "(masked)"
                : "not set"}
            </span>
          </label>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button onClick={saveProviderConfig} disabled={savingProvider}>
            {savingProvider ? "Saving..." : "Save Provider Settings"}
          </Button>
          <Button variant="ghost" onClick={clearOpenrouterApiKey} disabled={savingProvider}>
            Clear OpenRouter API Key
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
    </div>
  );
}
