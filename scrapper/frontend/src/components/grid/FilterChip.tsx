// Multi-select dropdown for column-level filters (city, tier, license_status, etc.)

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";

export type FilterOption = { value: string; n?: number };

export function FilterChip({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: FilterOption[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function toggle(v: string) {
    onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);
  }

  const active = selected.length > 0;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition",
          active
            ? "bg-primary/10 border-primary/30 text-primary"
            : "bg-card hover:bg-secondary",
        )}
      >
        <span>{label}</span>
        {active && (
          <span className="ml-0.5 inline-flex items-center justify-center rounded-full bg-primary text-primary-foreground text-[10px] h-4 min-w-4 px-1">
            {selected.length}
          </span>
        )}
        <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute z-30 mt-1 w-60 rounded-md border bg-popover text-popover-foreground shadow-lg overflow-hidden">
          <div className="max-h-72 overflow-y-auto py-1">
            {options.length === 0 && (
              <div className="px-3 py-2 text-xs text-muted-foreground">No values yet.</div>
            )}
            {options.map((opt) => {
              const isSel = selected.includes(opt.value);
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => toggle(opt.value)}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-secondary text-left"
                >
                  <span
                    className={cn(
                      "h-4 w-4 rounded border inline-flex items-center justify-center",
                      isSel ? "bg-primary border-primary text-primary-foreground" : "bg-background",
                    )}
                  >
                    {isSel && <Check className="h-3 w-3" />}
                  </span>
                  <span className="flex-1 truncate font-mono">{opt.value}</span>
                  {opt.n != null && (
                    <span className="text-muted-foreground tabular-nums">{opt.n.toLocaleString()}</span>
                  )}
                </button>
              );
            })}
          </div>
          {active && (
            <div className="border-t bg-muted/40 px-2 py-1.5">
              <button
                type="button"
                onClick={() => onChange([])}
                className="w-full inline-flex items-center justify-center gap-1 text-xs text-muted-foreground hover:text-foreground py-1"
              >
                <X className="h-3 w-3" />
                Clear
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function BoolChip({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean | undefined;
  onChange: (v: boolean | undefined) => void;
}) {
  function next() {
    if (value === undefined) onChange(true);
    else if (value === true) onChange(false);
    else onChange(undefined);
  }
  const display = value === undefined ? "any" : value ? "yes" : "no";
  return (
    <button
      type="button"
      onClick={next}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition",
        value !== undefined
          ? "bg-primary/10 border-primary/30 text-primary"
          : "bg-card hover:bg-secondary",
      )}
    >
      {label}: <span className="font-mono">{display}</span>
    </button>
  );
}
