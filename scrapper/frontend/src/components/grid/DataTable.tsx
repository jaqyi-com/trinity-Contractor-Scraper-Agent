// Generic server-driven data grid built on @tanstack/react-table.
// Pagination, sort, row click are all *controlled* — the page hosting the grid
// keeps the state and refetches when it changes.

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
  type OnChangeFn,
} from "@tanstack/react-table";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, ArrowUp, ArrowDown, ArrowUpDown, Loader2 } from "lucide-react";

export type DataTableProps<T> = {
  data: T[];
  columns: ColumnDef<T, any>[];
  total: number;
  pageIndex: number;
  pageSize: number;
  sorting: SortingState;
  onSortingChange: OnChangeFn<SortingState>;
  onPageChange: (index: number) => void;
  onPageSizeChange?: (size: number) => void;
  onRowClick?: (row: T) => void;
  isLoading?: boolean;
  isFetching?: boolean;
  emptyMessage?: string;
  rowKey?: (row: T) => string | number;
};

export function DataTable<T>({
  data,
  columns,
  total,
  pageIndex,
  pageSize,
  sorting,
  onSortingChange,
  onPageChange,
  onPageSizeChange,
  onRowClick,
  isLoading,
  isFetching,
  emptyMessage = "No results.",
  rowKey,
}: DataTableProps<T>) {
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
    pageCount: Math.max(1, Math.ceil(total / pageSize)),
  });

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const start = total === 0 ? 0 : pageIndex * pageSize + 1;
  const end = Math.min(total, (pageIndex + 1) * pageSize);

  return (
    <div className="rounded-lg border bg-card shadow-sm overflow-hidden">
      <div className="relative overflow-x-auto">
        {isFetching && !isLoading && (
          <div className="absolute top-0 right-0 m-2 z-10 inline-flex items-center gap-1.5 rounded-full bg-background border px-2 py-0.5 text-xs text-muted-foreground shadow-sm">
            <Loader2 className="h-3 w-3 animate-spin" /> Updating
          </div>
        )}
        <table className="w-full text-sm">
          <thead className="bg-muted/60 text-muted-foreground border-b">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => {
                  const canSort = h.column.getCanSort();
                  const sortDir = h.column.getIsSorted();
                  return (
                    <th
                      key={h.id}
                      className="text-left px-3 py-2.5 font-medium text-xs uppercase tracking-wide whitespace-nowrap"
                      style={{ width: h.getSize() !== 150 ? h.getSize() : undefined }}
                    >
                      {h.isPlaceholder ? null : (
                        <button
                          type="button"
                          disabled={!canSort}
                          onClick={h.column.getToggleSortingHandler()}
                          className={`inline-flex items-center gap-1 ${canSort ? "hover:text-foreground transition-colors" : ""}`}
                        >
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {canSort && (
                            sortDir === "asc"
                              ? <ArrowUp className="h-3 w-3" />
                              : sortDir === "desc"
                                ? <ArrowDown className="h-3 w-3" />
                                : <ArrowUpDown className="h-3 w-3 opacity-40" />
                          )}
                        </button>
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-10 text-center text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin inline-block mr-2" />
                  Loading…
                </td>
              </tr>
            )}
            {!isLoading && data.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-10 text-center text-muted-foreground">
                  {emptyMessage}
                </td>
              </tr>
            )}
            {!isLoading && table.getRowModel().rows.map((row) => (
              <tr
                key={rowKey ? rowKey(row.original) : row.id}
                onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                className={`border-b last:border-0 transition-colors ${onRowClick ? "cursor-pointer hover:bg-muted/40" : ""}`}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2.5 align-top">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer / pagination */}
      <div className="flex items-center justify-between gap-3 px-3 py-2 border-t bg-muted/30 text-xs text-muted-foreground">
        <div>
          {total === 0 ? "0 results" : <>Showing <span className="font-medium text-foreground">{start}</span>–<span className="font-medium text-foreground">{end}</span> of <span className="font-medium text-foreground">{total.toLocaleString()}</span></>}
        </div>
        <div className="flex items-center gap-2">
          {onPageSizeChange && (
            <label className="hidden sm:flex items-center gap-1.5">
              Rows per page:
              <select
                value={pageSize}
                onChange={(e) => onPageSizeChange(Number(e.target.value))}
                className="rounded border bg-background px-1.5 py-0.5 text-xs"
              >
                {[25, 50, 100, 200].map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </label>
          )}
          <div className="flex items-center gap-0.5">
            <PgBtn disabled={pageIndex === 0} onClick={() => onPageChange(0)} title="First"><ChevronsLeft className="h-3.5 w-3.5" /></PgBtn>
            <PgBtn disabled={pageIndex === 0} onClick={() => onPageChange(pageIndex - 1)} title="Prev"><ChevronLeft className="h-3.5 w-3.5" /></PgBtn>
            <span className="px-2 text-foreground font-medium">{pageIndex + 1} / {pageCount}</span>
            <PgBtn disabled={pageIndex + 1 >= pageCount} onClick={() => onPageChange(pageIndex + 1)} title="Next"><ChevronRight className="h-3.5 w-3.5" /></PgBtn>
            <PgBtn disabled={pageIndex + 1 >= pageCount} onClick={() => onPageChange(pageCount - 1)} title="Last"><ChevronsRight className="h-3.5 w-3.5" /></PgBtn>
          </div>
        </div>
      </div>
    </div>
  );
}

function PgBtn({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className="inline-flex h-7 w-7 items-center justify-center rounded hover:bg-secondary disabled:opacity-30 disabled:cursor-not-allowed transition"
    >
      {children}
    </button>
  );
}

/** Helper to translate TanStack's SortingState → backend sort params. */
export function sortingToParams(sorting: SortingState, fallback = { sort_by: "id", sort_dir: "desc" as const }) {
  if (!sorting.length) return fallback;
  const s = sorting[0];
  return { sort_by: s.id, sort_dir: (s.desc ? "desc" : "asc") as "asc" | "desc" };
}
