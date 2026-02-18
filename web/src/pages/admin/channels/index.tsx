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
  whatsappStatus,
} from "../../../api/endpoints";

export default function AdminChannelsPage() {
  const [pairNumber, setPairNumber] = useState("");
  const statusQuery = useQuery({
    queryKey: ["whatsapp-status"],
    queryFn: whatsappStatus,
    refetchInterval: 3000,
  });
  const qrQuery = useQuery({
    queryKey: ["whatsapp-qr"],
    queryFn: whatsappQrCode,
    enabled: false,
  });

  const createMutation = useMutation({ mutationFn: whatsappCreate, onSuccess: () => void statusQuery.refetch() });
  const disconnectMutation = useMutation({
    mutationFn: whatsappDisconnect,
    onSuccess: () => {
      void statusQuery.refetch();
      void qrQuery.refetch();
    },
  });
  const pairMutation = useMutation({ mutationFn: () => whatsappPairingCode(pairNumber) });

  const status = String(statusQuery.data?.status ?? (statusQuery.data?.payload as Record<string, unknown> | undefined)?.state ?? "unknown");
  const qr = String(qrQuery.data?.qrcode ?? "");

  return (
    <div>
      <Header title="Channels" subtitle="Manage WhatsApp Evolution pairing and status" />
      <Card className="mb-6">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={status === "open" || status === "connected" ? "success" : "warning"}>
            {status}
          </Badge>
          <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
            Create/Connect Instance
          </Button>
          <Button variant="secondary" onClick={() => void qrQuery.refetch()}>
            Load QR
          </Button>
          <Button variant="secondary" onClick={() => disconnectMutation.mutate()} disabled={disconnectMutation.isPending}>
            Disconnect
          </Button>
        </div>
      </Card>

      <Card className="mb-6" header={<h3 className="font-display text-base text-[var(--text-primary)]">Pairing Code</h3>}>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Input
            label="Phone Number"
            value={pairNumber}
            onChange={(e) => setPairNumber(e.target.value)}
            placeholder="15555550123"
          />
          <div className="flex items-end">
            <Button onClick={() => pairMutation.mutate()} disabled={pairMutation.isPending || !pairNumber.trim()}>
              Generate
            </Button>
          </div>
          <div className="flex items-end">
            <div className="rounded border border-[var(--border-default)] px-3 py-2 text-sm text-[var(--text-secondary)]">
              {String(pairMutation.data?.code ?? "-")}
            </div>
          </div>
        </div>
      </Card>

      <Card header={<h3 className="font-display text-base text-[var(--text-primary)]">QR Code</h3>}>
        {qr ? (
          <img src={qr.startsWith("data:") ? qr : `data:image/png;base64,${qr}`} alt="WhatsApp QR" className="max-w-xs rounded border border-[var(--border-default)]" />
        ) : (
          <p className="text-sm text-[var(--text-muted)]">No QR loaded.</p>
        )}
      </Card>
    </div>
  );
}
