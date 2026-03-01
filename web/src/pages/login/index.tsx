import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Button from "../../components/ui/Button";
import Input from "../../components/ui/Input";
import { login } from "../../api/endpoints";
import { useAuthStore } from "../../stores/auth";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const setAuth = useAuthStore((s) => s.setAuth);
  const navigate = useNavigate();

  const submit = async () => {
    setLoading(true);
    setError("");
    try {
      const result = await login(password);
      setAuth(result.user_id);
      navigate("/chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg p-4">
      <div className="w-full max-w-xs rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-8">
        <div className="mb-6 flex flex-col items-center gap-3">
          <div className="font-mono text-2xl font-bold text-accent">&gt;_</div>
          <div className="text-center">
            <h1 className="font-mono text-sm font-semibold uppercase tracking-widest text-text">
              JARVIS
            </h1>
            <p className="mt-1 font-mono text-xs text-text3">enter passphrase</p>
          </div>
        </div>
        <Input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="passphrase"
          onKeyDown={(e) => {
            if (e.key === "Enter" && password) submit();
          }}
        />
        {error ? (
          <p className="mt-2 font-mono text-xs text-danger">{error}</p>
        ) : null}
        <Button className="mt-4 w-full" onClick={submit} disabled={loading || !password}>
          {loading ? "authenticating..." : "authenticate"}
        </Button>
      </div>
    </div>
  );
}
