import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot } from "lucide-react";
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
      setAuth(result.token, result.user_id);
      navigate("/chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--bg-primary)] p-4">
      <div className="w-full max-w-sm animate-[fadeIn_0.4s_ease-out] rounded-2xl border border-[var(--border-default)] bg-surface p-8 shadow-xl">
        <div className="mb-6 flex flex-col items-center">
          <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#13293d] text-white dark:bg-slate-200 dark:text-slate-900">
            <Bot size={28} />
          </div>
          <h1 className="font-display text-2xl text-[var(--text-primary)]">Jarvis</h1>
          <p className="text-sm text-[var(--text-muted)]">Enter your password to continue</p>
        </div>
        <Input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          onKeyDown={(e) => {
            if (e.key === "Enter" && password) submit();
          }}
        />
        {error ? <p className="mt-2 text-sm text-ember">{error}</p> : null}
        <Button className="mt-4 w-full" onClick={submit} disabled={loading || !password}>
          {loading ? "Signing in..." : "Sign In"}
        </Button>
      </div>
    </div>
  );
}
