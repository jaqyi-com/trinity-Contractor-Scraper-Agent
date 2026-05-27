import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { History as HistoryIcon } from "lucide-react";
import { api } from "@/lib/api";
import { DataTable } from "@/components/grid/DataTable";
import { JobDrawer } from "@/components/drawer/JobDrawer";
import { Badge, PageHeader, EmptyValue } from "@/components/ui-bits";

function statusVariant(s?: string): "success" | "danger" | "info" | "warning" | "muted" {
  if (s === "completed") return "success";
  if (s === "failed") return "danger";
  if (s === "running" || s === "pending") return "info";
  if (s === "interrupted") return "warning";
  return "muted";
}

export default function History() {
  const { data = [], isLoading, isFetching } = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.listJobs(),
    refetchInterval: 5000,
  });

  const [selected, setSelected] = useState<any | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [sorting, setSorting] = useState<SortingState>([{ id: "started_at", desc: true }]);

  const sorted = useMemo(() => {
    const rows = [...data];
    if (sorting[0]) {
      const { id, desc } = sorting[0];
      rows.sort((a: any, b: any) => {
        const av = a[id], bv = b[id];
        if (av == null) return 1;
        if (bv == null) return -1;
        if (av < bv) return desc ? 1 : -1;
        if (av > bv) return desc ? -1 : 1;
        return 0;
      });
    }
    return rows;
  }, [data, sorting]);

  const pageRows = sorted.slice(pageIndex * pageSize, (pageIndex + 1) * pageSize);

  const columns = useMemo<ColumnDef<any, any>[]>(() => [
    { id: "job_id", accessorKey: "job_id", header: "Job ID",
      cell: ({ getValue }) => <code className="text-xs font-mono">{(getValue() as string).slice(0, 8)}…</code>,
    },
    { id: "status", accessorKey: "status", header: "Status",
      cell: ({ getValue }) => <Badge variant={statusVariant(getValue() as string)}>{getValue() as string}</Badge>,
    },
    { id: "current_stage", accessorKey: "current_stage", header: "Stage",
      cell: ({ getValue }) => {
        const v = getValue() as string | null;
        return v ? <code className="text-xs">{v}</code> : <EmptyValue />;
      },
    },
    { id: "started_at", accessorKey: "started_at", header: "Started",
      cell: ({ getValue }) => <span className="text-xs">{new Date(getValue() as string).toLocaleString()}</span>,
    },
    { id: "finished_at", accessorKey: "finished_at", header: "Finished",
      cell: ({ getValue }) => {
        const v = getValue() as string | null;
        return v ? <span className="text-xs">{new Date(v).toLocaleString()}</span> : <EmptyValue />;
      },
    },
    { id: "duration", header: "Duration", enableSorting: false,
      cell: ({ row }) => {
        const a = new Date(row.original.started_at).getTime();
        const b = row.original.finished_at ? new Date(row.original.finished_at).getTime() : Date.now();
        const sec = Math.floor((b - a) / 1000);
        const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
        return <span className="text-xs font-mono">{h ? `${h}h ` : ""}{m}m {s}s</span>;
      },
    },
  ], []);

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      <PageHeader
        title="History"
        subtitle="All past pipeline runs. Click any row for stage progress + errors."
        icon={<HistoryIcon className="h-6 w-6 text-primary" />}
      />

      <DataTable
        data={pageRows}
        columns={columns}
        total={sorted.length}
        pageIndex={pageIndex}
        pageSize={pageSize}
        sorting={sorting}
        onSortingChange={(u) => setSorting(typeof u === "function" ? u(sorting) : u)}
        onPageChange={setPageIndex}
        onPageSizeChange={(n) => { setPageSize(n); setPageIndex(0); }}
        onRowClick={setSelected}
        isLoading={isLoading}
        isFetching={isFetching}
        rowKey={(r: any) => r.job_id}
        emptyMessage="No jobs yet. Start one from the Dashboard."
      />

      <JobDrawer job={selected} open={!!selected} onClose={() => setSelected(null)} />
    </div>
  );
}
