import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import { api, type Keyword } from "@/lib/api";
import { Drawer, DrawerHeader, DrawerBody, DrawerSection, DrawerKV } from "./Drawer";
import { Badge, tierVariant, EmptyValue } from "@/components/ui-bits";

export function KeywordDrawer({
  keyword,
  open,
  onClose,
}: {
  keyword: Keyword | null;
  open: boolean;
  onClose: () => void;
}) {
  const history = useQuery({
    queryKey: ["keyword-history", keyword?.id],
    queryFn: () => api.keywordHistory(keyword!.id),
    enabled: !!keyword && open,
  });

  return (
    <Drawer open={open} onClose={onClose} width="w-[500px]">
      {keyword && (
        <>
          <DrawerHeader
            title={<span className="font-mono">{keyword.keyword}</span>}
            subtitle={`Keyword #${keyword.id}`}
            onClose={onClose}
            badge={
              <>
                <Badge variant={tierVariant(keyword.tier)}>{keyword.tier}</Badge>
                <Badge variant={keyword.active ? "success" : "muted"}>{keyword.active ? "Active" : "Inactive"}</Badge>
              </>
            }
          />
          <DrawerBody>
            <DrawerSection title="Details">
              <DrawerKV
                items={[
                  ["Tier", <Badge variant={tierVariant(keyword.tier)}>{keyword.tier}</Badge>],
                  ["Keyword", <code className="font-mono">{keyword.keyword}</code>],
                  ["Active", keyword.active ? "Yes" : "No"],
                  ["Notes", keyword.notes || <EmptyValue />],
                  ["Created by", keyword.created_by || <EmptyValue />],
                  ["Created at", new Date(keyword.created_at).toLocaleString()],
                  ["Updated at", new Date(keyword.updated_at).toLocaleString()],
                ]}
              />
            </DrawerSection>

            <DrawerSection title="Change history" count={history.data?.length}>
              {history.isLoading && <div className="text-xs text-muted-foreground">Loading…</div>}
              {history.data?.length === 0 && (
                <div className="text-xs text-muted-foreground italic">No changes recorded yet.</div>
              )}
              <div className="space-y-2">
                {history.data?.map((h: any) => (
                  <div key={h.id} className="rounded border bg-muted/30 p-3 text-xs">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge variant={
                        h.action === "CREATE" ? "success"
                          : h.action === "DELETE" ? "danger"
                          : h.action === "DEACTIVATE" ? "warning"
                          : "info"
                      }>{h.action}</Badge>
                      <span className="text-muted-foreground">
                        <History className="h-3 w-3 inline mr-1" />
                        {new Date(h.changed_at).toLocaleString()}
                      </span>
                    </div>
                    {h.changed_by && <div className="text-muted-foreground">by <code>{h.changed_by}</code></div>}
                    {h.reason && <div className="mt-1">{h.reason}</div>}
                  </div>
                ))}
              </div>
            </DrawerSection>
          </DrawerBody>
        </>
      )}
    </Drawer>
  );
}
