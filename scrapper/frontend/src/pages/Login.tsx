import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { LogIn, AlertCircle, Loader2 } from "lucide-react";
import { api, ApiError, tokenStore } from "@/lib/api";

export default function Login() {
  const nav = useNavigate();
  const loc = useLocation() as { state?: { from?: string } };
  const [email, setEmail] = useState("test@example.com");
  const [password, setPassword] = useState("123456");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.login({ email, password });
      tokenStore.set(res.access_token);
      const redirectTo = loc.state?.from || "/dashboard";
      nav(redirectTo, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail?.detail || err.detail?.error || "Invalid email or password");
      } else {
        setError((err as Error).message);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground mb-3">
            <LogIn className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-bold">Westpac Sales Scraper</h1>
          <p className="text-sm text-muted-foreground mt-1">Sign in to continue</p>
        </div>

        <form
          onSubmit={onSubmit}
          className="rounded-xl border bg-card p-6 shadow-sm space-y-4"
        >
          <div>
            <label className="text-sm font-medium block mb-1.5">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          <div>
            <label className="text-sm font-medium block mb-1.5">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-md bg-destructive/10 text-destructive p-3 text-sm">
              <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full inline-flex items-center justify-center gap-2 rounded-md bg-primary text-primary-foreground px-4 py-2.5 text-sm font-semibold hover:bg-primary/90 disabled:opacity-50 transition"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Signing in...
              </>
            ) : (
              <>
                <LogIn className="h-4 w-4" />
                Sign in
              </>
            )}
          </button>

          <div className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
            <div className="font-medium text-foreground mb-1">Test credentials</div>
            <div>Email: <code className="font-mono">test@example.com</code></div>
            <div>Password: <code className="font-mono">123456</code></div>
          </div>
        </form>
      </div>
    </div>
  );
}
