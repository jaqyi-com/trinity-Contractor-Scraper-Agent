import { History as HistoryIcon, Calendar, Activity } from "lucide-react";
import { Drawer, DrawerHeader, DrawerBody, DrawerSection, DrawerKV } from "./Drawer";
import { Badge } from "@/components/ui-bits";

function statusVariant(s?: string): "success" | "danger" | "info" | "warning" | "muted" {
  if (s === "completed") return "success";
  if (s === "failed") return "danger";
  if (s === "running" || s === "pending") return "info";
  if (s === "interrupted") return "warning";
  return "muted";
}

export function JobDrawer({
  job,
  open,
  onClose,
}: {
  job: any | null;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Drawer open={open} onClose={onClose} width="w-[560px]">
      {job && (
        <>
          <DrawerHeader
            title={<code className="text-sm font-mono">{job.job_id}</code>}
            subtitle={`Started ${new Date(job.started_at).toLocaleString()}`}
            onClose={onClose}
            badge={<Badge variant={statusVariant(job.status)}>{job.status}</Badge>}
          />
          <DrawerBody>
            <DrawerSection title="Status">
              <DrawerKV
                items={[
                  ["Status", <Badge variant={statusVariant(job.status)}>{job.status}</Badge>],
                  ["Current stage", job.current_stage ? <code className="text-xs">{job.current_stage}</code> : null],
                  ["Started at", <span className="text-xs"><Calendar className="h-3 w-3 inline mr-1" />{new Date(job.started_at).toLocaleString()}</span>],
                  ["Finished at", job.finished_at ? <span className="text-xs"><Calendar className="h-3 w-3 inline mr-1" />{new Date(job.finished_at).toLocaleString()}</span> : null],
                  ["Error", job.error ? <span className="text-destructive text-sm">{job.error}</span> : null],
                ]}
              />
            </DrawerSection>

            {job.stages_progress && (
              <DrawerSection title="Stage progress">
                <pre className="rounded border bg-muted/40 p-3 text-xs whitespace-pre-wrap break-words">
                  {JSON.stringify(job.stages_progress, null, 2)}
                </pre>
              </DrawerSection>
            )}

            {job.keywords_snapshot && (
              <DrawerSection title="Keyword snapshot" count={Array.isArray(job.keywords_snapshot) ? job.keywords_snapshot.length : undefined}>
                <p className="text-xs text-muted-foreground mb-1">
                  <Activity className="h-3 w-3 inline mr-1" />
                  Active keywords at job start.
                </p>
                <pre className="rounded border bg-muted/40 p-3 text-xs max-h-60 overflow-auto">
                  {JSON.stringify(job.keywords_snapshot, null, 2)}
                </pre>
              </DrawerSection>
            )}
          </DrawerBody>
        </>
      )}
    </Drawer>
  );
}
