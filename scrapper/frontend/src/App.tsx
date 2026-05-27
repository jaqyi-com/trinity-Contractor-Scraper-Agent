import { Routes, Route, NavLink, Navigate, useNavigate, useLocation } from "react-router-dom";
import { LayoutDashboard, Tags, Users, FileText, History as HistoryIcon, MapPin } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { api, tokenStore } from "@/lib/api";
import { Topbar } from "@/components/Topbar";
import Dashboard from "@/pages/Dashboard";
import Keywords from "@/pages/Keywords";
import Cities from "@/pages/Cities";
import Results from "@/pages/Results";
import Logs from "@/pages/Logs";
import History from "@/pages/History";
import Login from "@/pages/Login";

const nav = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/cities", label: "Cities", icon: MapPin },
  { to: "/keywords", label: "Keywords", icon: Tags },
  { to: "/results", label: "Results", icon: Users },
  { to: "/logs", label: "Logs", icon: FileText },
  { to: "/history", label: "History", icon: HistoryIcon },
];

/** Guard: validates token on mount, redirects to /login if missing/invalid. */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const loc = useLocation();
  const [state, setState] = useState<"checking" | "ok" | "denied">("checking");
  const [user, setUser] = useState<{ email: string; name?: string } | null>(null);

  useEffect(() => {
    const token = tokenStore.get();
    if (!token) {
      setState("denied");
      navigate("/login", { replace: true, state: { from: loc.pathname } });
      return;
    }
    api
      .me()
      .then((u) => {
        setUser(u);
        setState("ok");
      })
      .catch(() => {
        // api.ts already cleared the token + redirected on 401
        setState("denied");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (state === "checking") {
    return (
      <div className="min-h-screen flex items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }
  if (state === "denied") return null;

  return <Shell user={user}>{children}</Shell>;
}

function Shell({ user, children }: { user: { email: string; name?: string } | null; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="w-60 border-r bg-card flex flex-col shrink-0">
        <div className="px-5 py-4 border-b">
          <div className="font-semibold text-base flex items-center gap-2">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground text-xs font-bold">CS</span>
            Contractor Scraper
          </div>
          <div className="text-[10px] text-muted-foreground mt-1 ml-9">Florida Lead Gen</div>
        </div>
        <nav className="flex-1 p-2.5 space-y-0.5 overflow-y-auto">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 px-2.5 py-2 rounded-md text-sm font-medium transition-colors",
                  isActive
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 border-t text-[10px] text-muted-foreground">v0.1.0 — dev</div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <Topbar user={user} />
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route
        path="/dashboard"
        element={
          <RequireAuth>
            <Dashboard />
          </RequireAuth>
        }
      />
      <Route
        path="/cities"
        element={
          <RequireAuth>
            <Cities />
          </RequireAuth>
        }
      />
      <Route
        path="/keywords"
        element={
          <RequireAuth>
            <Keywords />
          </RequireAuth>
        }
      />
      <Route
        path="/results"
        element={
          <RequireAuth>
            <Results />
          </RequireAuth>
        }
      />
      <Route
        path="/logs"
        element={
          <RequireAuth>
            <Logs />
          </RequireAuth>
        }
      />
      <Route
        path="/history"
        element={
          <RequireAuth>
            <History />
          </RequireAuth>
        }
      />
    </Routes>
  );
}
