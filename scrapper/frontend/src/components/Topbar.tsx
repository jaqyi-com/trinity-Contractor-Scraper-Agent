import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LogOut, ChevronDown, User } from "lucide-react";
import { tokenStore } from "@/lib/api";

export function Topbar({ user }: { user: { email: string; name?: string } | null }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function logout() {
    tokenStore.clear();
    navigate("/login", { replace: true });
  }

  if (!user) return null;
  const initials = (user.name || user.email).slice(0, 2).toUpperCase();

  return (
    <header className="h-12 border-b bg-card flex items-center justify-end px-4 shrink-0 sticky top-0 z-30 backdrop-blur supports-[backdrop-filter]:bg-card/90">
      <div ref={ref} className="relative">
        <button
          onClick={() => setOpen((o) => !o)}
          className="inline-flex items-center gap-2 rounded-md px-2 py-1 hover:bg-secondary transition"
        >
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">
            {initials}
          </span>
          <span className="hidden sm:flex flex-col items-start leading-tight">
            <span className="text-xs font-medium">{user.name || user.email}</span>
            <span className="text-[10px] text-muted-foreground">{user.email}</span>
          </span>
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        </button>

        {open && (
          <div className="absolute right-0 mt-1 w-56 rounded-md border bg-popover text-popover-foreground shadow-lg overflow-hidden z-50">
            <div className="px-3 py-2.5 border-b">
              <div className="text-xs font-medium truncate">{user.name || "Signed in"}</div>
              <div className="text-[11px] text-muted-foreground truncate">{user.email}</div>
            </div>
            <button
              disabled
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground"
            >
              <User className="h-3.5 w-3.5" /> Account
              <span className="ml-auto text-[10px]">soon</span>
            </button>
            <button
              onClick={logout}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-secondary text-left"
            >
              <LogOut className="h-3.5 w-3.5" /> Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
