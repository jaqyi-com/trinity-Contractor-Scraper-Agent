// Slide-in right-side drawer used for entity detail views.
// Composable: <Drawer>{children}</Drawer> with header / body sections.

import { useEffect } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export function Drawer({
  open,
  onClose,
  width = "w-[480px]",
  children,
}: {
  open: boolean;
  onClose: () => void;
  width?: string;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  return (
    <>
      {/* Backdrop */}
      <div
        aria-hidden
        onClick={onClose}
        className={cn(
          "fixed inset-0 bg-black/30 backdrop-blur-[2px] z-40 transition-opacity",
          open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none",
        )}
      />
      {/* Panel */}
      <aside
        className={cn(
          "fixed top-0 right-0 h-screen bg-card border-l shadow-xl z-50 flex flex-col transition-transform",
          width,
          "max-w-[100vw]",
          open ? "translate-x-0" : "translate-x-full",
        )}
        role="dialog"
        aria-modal="true"
      >
        {children}
      </aside>
    </>
  );
}

export function DrawerHeader({
  title,
  subtitle,
  onClose,
  badge,
  actions,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  onClose: () => void;
  badge?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="px-5 py-4 border-b flex items-start gap-3 shrink-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="font-semibold text-base truncate">{title}</h2>
          {badge}
        </div>
        {subtitle && <div className="text-xs text-muted-foreground mt-0.5 truncate">{subtitle}</div>}
      </div>
      {actions}
      <button
        onClick={onClose}
        className="h-7 w-7 inline-flex items-center justify-center rounded-md hover:bg-secondary text-muted-foreground"
        aria-label="Close"
      >
        <X className="h-4 w-4" />
      </button>
    </header>
  );
}

export function DrawerBody({ children }: { children: React.ReactNode }) {
  return <div className="flex-1 overflow-y-auto p-5 space-y-5">{children}</div>;
}

export function DrawerSection({
  title,
  children,
  count,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="text-[11px] uppercase tracking-wider text-muted-foreground font-semibold mb-2 flex items-center gap-2">
        {title}
        {count != null && <span className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] tabular-nums normal-case">{count}</span>}
      </h3>
      {children}
    </section>
  );
}

/** Two-column key/value list. Skips empty values. */
export function DrawerKV({ items }: { items: [string, React.ReactNode][] }) {
  const filtered = items.filter(([_, v]) => v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0));
  if (filtered.length === 0) return <div className="text-xs text-muted-foreground italic">No data.</div>;
  return (
    <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-2 text-sm">
      {filtered.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-xs text-muted-foreground self-start pt-0.5">{k}</dt>
          <dd className="break-words min-w-0">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
