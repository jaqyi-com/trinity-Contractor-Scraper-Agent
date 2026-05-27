import { MapPin, Hash, Calendar } from "lucide-react";
import type { City } from "@/lib/api";
import { Drawer, DrawerHeader, DrawerBody, DrawerSection, DrawerKV } from "./Drawer";
import { Badge, EmptyValue } from "@/components/ui-bits";

export function CityDrawer({
  city,
  open,
  onClose,
}: {
  city: City | null;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Drawer open={open} onClose={onClose} width="w-[480px]">
      {city && (
        <>
          <DrawerHeader
            title={city.name}
            subtitle={`${city.state} · ${city.zips.length} ZIP${city.zips.length === 1 ? "" : "s"}`}
            onClose={onClose}
            badge={<Badge variant="info">{city.state}</Badge>}
          />
          <DrawerBody>
            <DrawerSection title="Identity">
              <DrawerKV
                items={[
                  ["ID", <code className="text-xs">{city.id}</code>],
                  ["Name", city.name],
                  ["State", city.state],
                  ["Total ZIPs", city.zips.length],
                  ["Created", <span className="text-xs"><Calendar className="h-3 w-3 inline mr-1" />{new Date(city.created_at).toLocaleString()}</span>],
                  ["Updated", <span className="text-xs"><Calendar className="h-3 w-3 inline mr-1" />{new Date(city.updated_at).toLocaleString()}</span>],
                ]}
              />
            </DrawerSection>

            <DrawerSection title="ZIP codes" count={city.zips.length}>
              {city.zips.length === 0 ? (
                <div className="text-xs text-muted-foreground italic"><EmptyValue /> No ZIPs configured.</div>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {city.zips.map((z) => (
                    <span key={z} className="inline-flex items-center gap-1 rounded-full bg-secondary text-secondary-foreground px-2.5 py-1 text-xs font-mono">
                      <Hash className="h-3 w-3 opacity-60" />
                      {z}
                    </span>
                  ))}
                </div>
              )}
              <p className="text-xs text-muted-foreground mt-3">
                <MapPin className="h-3 w-3 inline mr-1" />
                Edit ZIPs from the card on the Cities page.
              </p>
            </DrawerSection>
          </DrawerBody>
        </>
      )}
    </Drawer>
  );
}
