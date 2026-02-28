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

type ProviderName = "openrouter" | "sglang" | "lmstudio";

function normalizeProvider(value: string): ProviderName {
  if (value === "sglang" || value === "lmstudio") return value;
  return "openrouter";
}

const selectCls =
  "w-full rounded-md border border-[var(--color-border-2)] bg-[var(--color-surface-2)] px-3 py-2 font-mono text-sm text-text outline-none focus:border-accent";

export default function AdminProvidersPage() {
  const providerQuery = useQuery({
    queryKey: ["provider-config"],
    queryFn: getProviderConfig,
  });
  const modelCatalogQuery = useQuery({
    queryKey: ["provider-models-catalog"],
    queryFn: getProviderModelsCatalog,
  });

  const [primaryProvider, setPrimaryProvider] = useState<ProviderName>("openrouter");
  const [fallbackProvider, setFallbackProvider] = useState<ProviderName>("sglang");
  const [openrouterModel, setOpenrouterModel] = useState("");
  const [sglangModel, setSglangModel] = useState("");
  const [lmstudioModel, setLmstudioModel] = useState("");
  const [lmstudioBaseUrl, setLmstudioBaseUrl] = useState("");
  const [openrouterApiKey, setOpenrouterApiKey] = useState("");
  const [lmstudioApiKey, setLmstudioApiKey] = useState("");
  const [savingProvider, setSavingProvider] = useState(false);
  const [providerStatus, setProviderStatus] = useState("");
  const [providerDetail, setProviderDetail] = useState("");

  useEffect(() => {
    if (!providerQuery.data) return;
    setPrimaryProvider(normalizeProvider(providerQuery.data.primary_provider));
    setFallbackProvider(normalizeProvider(providerQuery.data.fallback_provider));
    setOpenrouterModel(providerQuery.data.openrouter_model);
    setSglangModel(providerQuery.data.sglang_model);
    setLmstudioModel(providerQuery.data.lmstudio_model);
    setLmstudioBaseUrl(providerQuery.data.lmstudio_base_url);
    setOpenrouterApiKey("");
    setLmstudioApiKey("");
  }, [providerQuery.data]);

  const saveProviderConfig = async () => {
    setSavingProvider(true);
    setProviderStatus("saving");
    setProviderDetail("");
    try {
      const payload: {
        primary_provider: ProviderName;
        fallback_provider: ProviderName;
        openrouter_model: string;
        sglang_model: string;
        lmstudio_model: string;
        lmstudio_base_url: string;
        openrouter_api_key?: string;
        lmstudio_api_key?: string;
      } = {
        primary_provider: primaryProvider,
        fallback_provider: fallbackProvider,
        openrouter_model: openrouterModel.trim(),
        sglang_model: sglangModel.trim(),
        lmstudio_model: lmstudioModel.trim(),
        lmstudio_base_url: lmstudioBaseUrl.trim(),
      };
      const trimmedOpenrouterApiKey = openrouterApiKey.trim();
      if (trimmedOpenrouterApiKey) payload.openrouter_api_key = trimmedOpenrouterApiKey;
      const trimmedLmstudioApiKey = lmstudioApiKey.trim();
      if (trimmedLmstudioApiKey) payload.lmstudio_api_key = trimmedLmstudioApiKey;
      const result = await updateProviderConfig({
        ...payload,
      });
      setProviderStatus("success");
      setProviderDetail(
        `Saved provider config (primary=${result.primary_provider}, fallback=${result.fallback_provider}, OpenRouter=${result.openrouter_model}, SGLang=${result.sglang_model}, LM Studio=${result.lmstudio_model}, OpenRouter key=${result.openrouter_api_key_set ? "set" : "not set"}, LM Studio key=${result.lmstudio_api_key_set ? "set" : "not set"}). Auto-reload: API=${result.api_reloaded}, worker queue=${result.worker_reload_enqueued}.`,
      );
      setOpenrouterApiKey("");
      setLmstudioApiKey("");
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

  const clearLmstudioApiKey = async () => {
    setSavingProvider(true);
    setProviderStatus("saving");
    setProviderDetail("");
    try {
      const result = await updateProviderConfig({
        clear_lmstudio_api_key: true,
      });
      setProviderStatus("success");
      setProviderDetail(
        `Cleared LM Studio API key. Auto-reload: API=${result.api_reloaded}, worker queue=${result.worker_reload_enqueued}.`,
      );
      setLmstudioApiKey("");
      void providerQuery.refetch();
    } catch (err) {
      setProviderStatus("error");
      setProviderDetail(err instanceof Error ? err.message : "Failed to clear LM Studio API key");
    } finally {
      setSavingProvider(false);
    }
  };

  const providerOptions = (providerQuery.data?.available_primary_providers.length
    ? providerQuery.data.available_primary_providers
    : ["openrouter", "sglang", "lmstudio"]
  ).map(normalizeProvider);
  const fallbackOptions = providerOptions.filter((item) => item !== primaryProvider);

  return (
    <div>
      <Header
        title="Providers"
        subtitle="Provider routing and model selection"
        icon={<Server className="h-5 w-5" />}
      />

      <Card
        className="mb-6"
        header={
          <div className="flex items-center gap-2">
            <Server className="h-4 w-4 text-accent" />
            <span className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">
              Model Routing
            </span>
          </div>
        }
      >
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <label className="text-sm">
            <span className="mb-1 block font-mono text-xs font-medium text-text2">Primary Provider</span>
            <select
              className={selectCls}
              value={primaryProvider}
              onChange={(e) => setPrimaryProvider(normalizeProvider(e.target.value))}
            >
              {providerOptions.map((item) => (
                <option key={item} value={item}>
                  {item === "openrouter"
                    ? "OpenRouter"
                    : item === "sglang"
                      ? "SGLang (local)"
                      : "LM Studio (local)"}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-mono text-xs font-medium text-text2">
              Fallback Provider
            </span>
            <select
              className={selectCls}
              value={fallbackProvider}
              onChange={(e) => setFallbackProvider(normalizeProvider(e.target.value))}
            >
              {fallbackOptions.map((item) => (
                <option key={item} value={item}>
                  {item === "openrouter"
                    ? "OpenRouter"
                    : item === "sglang"
                      ? "SGLang (local)"
                      : "LM Studio (local)"}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-mono text-xs font-medium text-text2">OpenRouter Model</span>
            <Input
              value={openrouterModel}
              onChange={(e) => setOpenrouterModel(e.target.value)}
              placeholder="google/gemini-2.5-flash"
            />
            <span className="mt-1 block font-mono text-xs text-text3">
              Any model ID available on openrouter.ai
            </span>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-mono text-xs font-medium text-text2">SGLang Model</span>
            <select
              className={selectCls}
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
            <span className="mt-1 block font-mono text-xs text-text3">
              Source: {modelCatalogQuery.data?.sglang_source || "configured value"}
            </span>
          </label>
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
          <label className="text-sm">
            <span className="mb-1 block font-mono text-xs font-medium text-text2">LM Studio Model</span>
            <select
              className={selectCls}
              value={lmstudioModel}
              onChange={(e) => setLmstudioModel(e.target.value)}
            >
              {(modelCatalogQuery.data?.lmstudio_models.length
                ? modelCatalogQuery.data.lmstudio_models
                : [lmstudioModel || "local-model"]
              ).map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
            <span className="mt-1 block font-mono text-xs text-text3">
              Source: {modelCatalogQuery.data?.lmstudio_source || "configured value"}
            </span>
          </label>
          <label className="text-sm md:col-span-2">
            <span className="mb-1 block font-mono text-xs font-medium text-text2">LM Studio Base URL</span>
            <Input
              value={lmstudioBaseUrl}
              onChange={(e) => setLmstudioBaseUrl(e.target.value)}
              placeholder="http://127.0.0.1:1234/v1"
            />
          </label>
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
          <label className="text-sm md:col-span-2">
            <span className="mb-1 block font-mono text-xs font-medium text-text2">OpenRouter API Key</span>
            <Input
              type="password"
              value={openrouterApiKey}
              onChange={(e) => setOpenrouterApiKey(e.target.value)}
              placeholder="sk-or-v1-..."
            />
            <span className="mt-1 block font-mono text-xs text-text3">
              Current:{" "}
              {providerQuery.data?.openrouter_api_key_set
                ? providerQuery.data.openrouter_api_key_masked || "(masked)"
                : "not set"}
            </span>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-mono text-xs font-medium text-text2">LM Studio API Key</span>
            <Input
              type="password"
              value={lmstudioApiKey}
              onChange={(e) => setLmstudioApiKey(e.target.value)}
              placeholder="optional"
            />
            <span className="mt-1 block font-mono text-xs text-text3">
              Current:{" "}
              {providerQuery.data?.lmstudio_api_key_set
                ? providerQuery.data.lmstudio_api_key_masked || "(masked)"
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
          <Button variant="ghost" onClick={clearLmstudioApiKey} disabled={savingProvider}>
            Clear LM Studio API Key
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
                ? "border-success/30 bg-success-dim"
                : providerStatus === "error"
                  ? "border-danger/30 bg-danger-dim"
                  : "border-[var(--color-border)] bg-surface-2"
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
              <p className="font-mono text-xs text-text2">{providerDetail}</p>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
