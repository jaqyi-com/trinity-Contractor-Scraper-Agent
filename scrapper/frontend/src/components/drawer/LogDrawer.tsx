import { FileText } from "lucide-react";
import type { ClassificationLog } from "@/lib/api";
import { Drawer, DrawerHeader, DrawerBody, DrawerSection, DrawerKV } from "./Drawer";
import { Badge, tierVariant, decisionVariant, EmptyValue } from "@/components/ui-bits";

export function LogDrawer({
  log,
  open,
  onClose,
}: {
  log: ClassificationLog | null;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Drawer open={open} onClose={onClose} width="w-[540px]">
      {log && (
        <>
          <DrawerHeader
            title={log.business_name || "Classification entry"}
            subtitle={`Log #${log.id} · ${new Date(log.created_at).toLocaleString()}`}
            onClose={onClose}
            badge={
              <>
                <Badge variant={decisionVariant(log.decision)}>{log.decision}</Badge>
                {log.assigned_tier && <Badge variant={tierVariant(log.assigned_tier)}>{log.assigned_tier}</Badge>}
              </>
            }
          />

          <DrawerBody>
            <DrawerSection title="Reason">
              {log.reason ? (
                <p className="text-sm">{log.reason}</p>
              ) : (
                <div className="text-xs text-muted-foreground italic">No reason recorded.</div>
              )}
            </DrawerSection>

            <DrawerSection title="Matched keywords" count={log.matched_keywords?.length ?? 0}>
              {log.matched_keywords?.length ? (
                <div className="flex flex-wrap gap-1">
                  {log.matched_keywords.map((k, i) => (
                    <Badge key={`${k.keyword}-${i}`} variant="success" className="cursor-default">
                      {k.keyword}
                      {k.tier && <span className="opacity-60 ml-1">· {k.tier}</span>}
                    </Badge>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-muted-foreground italic">None.</div>
              )}
            </DrawerSection>

            <DrawerSection title="Exclusion hits" count={log.exclusion_keywords?.length ?? 0}>
              {log.exclusion_keywords?.length ? (
                <div className="flex flex-wrap gap-1">
                  {log.exclusion_keywords.map((k, i) => (
                    <Badge key={`${k.keyword}-${i}`} variant="danger" className="cursor-default">
                      {k.keyword}
                      {k.tier && <span className="opacity-60 ml-1">· {k.tier}</span>}
                    </Badge>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-muted-foreground italic">None.</div>
              )}
            </DrawerSection>

            <DrawerSection title="Classifier input">
              {log.classifier_text ? (
                <pre className="rounded border bg-muted/40 p-3 text-xs whitespace-pre-wrap break-words font-mono leading-relaxed">
                  {log.classifier_text}
                </pre>
              ) : (
                <div className="text-xs text-muted-foreground italic">No input text recorded.</div>
              )}
            </DrawerSection>

            <DrawerSection title="Meta">
              <DrawerKV
                items={[
                  ["Log ID", <code className="text-xs">{log.id}</code>],
                  ["Contractor ID", log.contractor_id ? <code className="text-xs">{log.contractor_id}</code> : <EmptyValue />],
                  ["Place ID", log.place_id ? <code className="text-xs break-all">{log.place_id}</code> : <EmptyValue />],
                  ["Job ID", <code className="text-xs break-all">{log.job_id}</code>],
                  ["Created at", <span className="text-xs"><FileText className="h-3 w-3 inline mr-1" />{new Date(log.created_at).toLocaleString()}</span>],
                ]}
              />
            </DrawerSection>
          </DrawerBody>
        </>
      )}
    </Drawer>
  );
}
