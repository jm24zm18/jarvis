import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import Header from "../../../components/layout/Header";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import Input from "../../../components/ui/Input";
import Badge from "../../../components/ui/Badge";
import {
  whatsappCreate,
  whatsappDisconnect,
  whatsappPairingCode,
  whatsappQrCode,
  whatsappReset,
  whatsappRestart,
  whatsappStatus,
  telegramStatus,
} from "../../../api/endpoints";

export default function AdminChannelsPage() {
  const [pairNumber, setPairNumber] = useState("");

  const statusQuery = useQuery({
    queryKey: ["whatsapp-status"],
    queryFn: whatsappStatus,
    refetchInterval: 3000,
  });

  const status = String(statusQuery.data?.status ?? (statusQuery.data?.payload as Record<string, unknown> | undefined)?.state ?? "unknown");
  const diagnostics = (statusQuery.data?.diagnostics as Record<string, unknown> | undefined) ?? {};
  const disconnectCode = typeof diagnostics.disconnect_code === "number" ? diagnostics.disconnect_code : null;
  const disconnectReason = String(diagnostics.disconnect_reason ?? "");
  const relinkRequired = Boolean(diagnostics.relink_required);
  const canReconnect = diagnostics.can_reconnect !== false;
  const recoverable = diagnostics.recoverable !== false;
  const pairingRequired = relinkRequired || !recoverable || !canReconnect;

  const qrQuery = useQuery({
    queryKey: ["whatsapp-qr"],
    queryFn: whatsappQrCode,
    enabled: status === "qr",
    refetchInterval: status === "qr" ? 2000 : false,
  });

  const tgQuery = useQuery({
    queryKey: ["telegram-status"],
    queryFn: telegramStatus,
    refetchInterval: 10000,
  });

  const createMutation = useMutation({ mutationFn: whatsappCreate, onSuccess: () => void statusQuery.refetch() });
  const resetMutation = useMutation({
    mutationFn: whatsappReset,
    onSuccess: () => {
      void statusQuery.refetch();
      void qrQuery.refetch();
    },
  });
  const disconnectMutation = useMutation({
    mutationFn: whatsappDisconnect,
    onSuccess: () => {
      void statusQuery.refetch();
      void qrQuery.refetch();
    },
  });
  const restartMutation = useMutation({
    mutationFn: whatsappRestart,
    onSuccess: () => {
      // Poll for container to come back up (takes ~3-5s with Docker)
      setTimeout(() => void statusQuery.refetch(), 4000);
    },
  });
  const pairMutation = useMutation({ mutationFn: () => whatsappPairingCode(pairNumber) });
  const qr = String(qrQuery.data?.qrcode ?? "");
  const canGeneratePairingCode = status === "qr" && pairNumber.trim().length > 0;
  const lifecycleBusy =
    createMutation.isPending ||
    resetMutation.isPending ||
    disconnectMutation.isPending ||
    restartMutation.isPending;

  const tgEnabled = Boolean(tgQuery.data?.enabled);
  const tgToken = Boolean(tgQuery.data?.token_configured);
  const tgChats = String(tgQuery.data?.allowed_chat_ids || "");

  return (
    <div>
      <Header title="Channels" subtitle="Manage configured messaging channels" />

      <h2 className="mb-4 font-mono text-xl text-text">Telegram (Bot API)</h2>
      <Card className="mb-8">
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-2">
            Status: <Badge variant={tgEnabled ? "success" : "warning"}>{tgEnabled ? "enabled" : "disabled"}</Badge>
          </div>
          <div className="text-sm text-text2">
            <p className="mb-1"><strong>Bot Token:</strong> {tgToken ? "Configured (Hidden)" : "Not configured in environment"}</p>
            <p><strong>Allowed Chat IDs:</strong> {tgChats || "None configured"}</p>
          </div>
          {!tgEnabled && (
            <p className="text-xs text-text3">
              Set TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_IDS in your production environment to enable.
            </p>
          )}
        </div>
      </Card>

      <h2 className="mb-4 font-mono text-xl text-text">WhatsApp (Baileys Node Server)</h2>
      <Card className="mb-6">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={status === "open" || status === "connected" ? "success" : "warning"}>
            {status}
          </Badge>
          <Button
            onClick={() => {
              createMutation.mutate();
            }}
            disabled={lifecycleBusy}
          >
            Initialize Connection
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              void qrQuery.refetch();
            }}
            disabled={lifecycleBusy}
          >
            Load QR
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              resetMutation.mutate();
            }}
            disabled={lifecycleBusy}
          >
            Force Re-pair
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              disconnectMutation.mutate();
            }}
            disabled={lifecycleBusy}
          >
            Disconnect
          </Button>
          <Button
            variant="secondary"
            onClick={() => restartMutation.mutate()}
            disabled={lifecycleBusy}
          >
            {restartMutation.isPending ? "Restarting..." : "Restart Server"}
          </Button>
        </div>
        {status !== "open" && (disconnectCode !== null || disconnectReason) ? (
          <p className="mt-3 text-sm text-text2">
            Last disconnect: {disconnectCode !== null ? `HTTP ${disconnectCode}` : "unknown"}{disconnectReason ? ` (${disconnectReason})` : ""}{pairingRequired ? ". Re-pair required." : "."}
          </p>
        ) : null}
        {pairingRequired ? (
          <p className="mt-2 text-sm text-text2">
            Session logged out; run Force Re-pair and scan a new QR code.
          </p>
        ) : null}
      </Card>

      <Card className="mb-6" header={<h3 className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">Pairing Code</h3>}>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Input
            label="Phone Number"
            value={pairNumber}
            onChange={(e) => setPairNumber(e.target.value)}
            placeholder="15555550123"
          />
          <div className="flex items-end">
            <Button onClick={() => pairMutation.mutate()} disabled={pairMutation.isPending || !canGeneratePairingCode}>
              Generate
            </Button>
          </div>
          <div className="flex items-end">
            <div className="rounded border border-[var(--color-border)] px-3 py-2 text-sm text-text2">
              {pairMutation.isPending
                ? "Generating..."
                : pairMutation.isError
                  ? `Error: ${String((pairMutation.error as Error)?.message ?? "unknown")}`
                  : status !== "qr"
                    ? pairingRequired
                      ? `QR not ready (state: ${status}). Session logged out; use Force Re-pair, then wait for QR.`
                      : `QR not ready (state: ${status}). Initialize connection and wait for QR.`
                  : String(pairMutation.data?.code ?? "-")}
            </div>
          </div>
        </div>
      </Card>

      <Card header={<h3 className="font-mono text-xs font-semibold uppercase tracking-widest text-text2">QR Code</h3>}>
        {qr ? (
          <img src={qr.startsWith("data:") ? qr : `data:image/png;base64,${qr}`} alt="WhatsApp QR" className="max-w-xs rounded border border-[var(--color-border)]" />
        ) : (
          <p className="text-sm text-text3">No QR loaded.</p>
        )}
      </Card>
    </div>
  );
}
