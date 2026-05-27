import { useQuery } from "@tanstack/react-query";
import { Globe, Phone, Mail, MapPin, Star, ShieldCheck, ShieldAlert, Calendar, User, ExternalLink } from "lucide-react";
import { api, type Contractor } from "@/lib/api";
import { Drawer, DrawerHeader, DrawerBody, DrawerSection, DrawerKV } from "./Drawer";
import { Badge, tierVariant, licenseVariant, decisionVariant, EmptyValue } from "@/components/ui-bits";

export function ContractorDrawer({
  contractor,
  open,
  onClose,
}: {
  contractor: Contractor | null;
  open: boolean;
  onClose: () => void;
}) {
  const classification = useQuery({
    queryKey: ["contractor-classification", contractor?.id],
    queryFn: () => api.contractorClassification(contractor!.id),
    enabled: !!contractor && open,
  });

  return (
    <Drawer open={open} onClose={onClose} width="w-[560px]">
      {contractor && (
        <>
          <DrawerHeader
            title={contractor.business_name}
            subtitle={[contractor.city, contractor.zip_code].filter(Boolean).join(" · ")}
            onClose={onClose}
            badge={
              <>
                {contractor.tier && <Badge variant={tierVariant(contractor.tier)}>{contractor.tier}</Badge>}
                {contractor.license_status && (
                  <Badge variant={licenseVariant(contractor.license_status)}>
                    {contractor.license_status}
                  </Badge>
                )}
              </>
            }
          />

          <DrawerBody>
            {/* Quick contact card */}
            <div className="rounded-lg border bg-muted/30 p-3 space-y-2 text-sm">
              <Line icon={<Phone className="h-3.5 w-3.5" />} value={contractor.phone}>
                {contractor.phone && <a href={`tel:${contractor.phone}`} className="hover:underline">{contractor.phone}</a>}
              </Line>
              <Line icon={<Mail className="h-3.5 w-3.5" />} value={contractor.email}>
                {contractor.email && <a href={`mailto:${contractor.email}`} className="hover:underline break-all">{contractor.email}</a>}
              </Line>
              <Line icon={<Globe className="h-3.5 w-3.5" />} value={contractor.website}>
                {contractor.website && (
                  <a href={contractor.website} target="_blank" rel="noreferrer" className="hover:underline inline-flex items-center gap-1 break-all">
                    {contractor.website}
                    <ExternalLink className="h-3 w-3 shrink-0" />
                  </a>
                )}
              </Line>
              <Line icon={<MapPin className="h-3.5 w-3.5" />} value={contractor.address}>
                {contractor.address}
              </Line>
              <Line icon={<User className="h-3.5 w-3.5" />} value={contractor.owner_name}>
                {contractor.owner_name}
              </Line>
            </div>

            {/* Ratings + reviews */}
            <DrawerSection title="Ratings">
              <div className="grid grid-cols-2 gap-3">
                <RatingCard
                  icon={<Star className="h-4 w-4 text-amber-500" />}
                  label="Google"
                  value={contractor.google_rating}
                  hint={contractor.google_review_count ? `${contractor.google_review_count} reviews` : null}
                />
                <RatingCard
                  icon={contractor.bbb_accredited ? <ShieldCheck className="h-4 w-4 text-emerald-600" /> : <ShieldAlert className="h-4 w-4 text-muted-foreground" />}
                  label="BBB"
                  value={contractor.bbb_rating}
                  hint={contractor.bbb_accredited ? "Accredited" : contractor.bbb_accredited === false ? "Not accredited" : null}
                />
              </div>
            </DrawerSection>

            {/* License info */}
            {(contractor.license_numbers?.length || contractor.license_categories?.length) && (
              <DrawerSection title="License">
                <DrawerKV
                  items={[
                    ["Status", contractor.license_status && <Badge variant={licenseVariant(contractor.license_status)}>{contractor.license_status}</Badge>],
                    ["Numbers", contractor.license_numbers?.length ? (
                      <div className="flex flex-wrap gap-1">
                        {contractor.license_numbers.map((n) => <code key={n} className="rounded bg-muted px-1.5 py-0.5 text-xs">{n}</code>)}
                      </div>
                    ) : null],
                    ["Categories", contractor.license_categories?.length ? (
                      <div className="flex flex-wrap gap-1">
                        {contractor.license_categories.map((c) => <Badge key={c} variant="muted">{c}</Badge>)}
                      </div>
                    ) : null],
                  ]}
                />
              </DrawerSection>
            )}

            {/* Categories + keywords */}
            <DrawerSection title="Discovery">
              <DrawerKV
                items={[
                  ["Categories", contractor.google_categories?.length ? (
                    <div className="flex flex-wrap gap-1">
                      {contractor.google_categories.map((c) => <Badge key={c} variant="info">{c}</Badge>)}
                    </div>
                  ) : null],
                  ["Services", contractor.services_listed?.length ? (
                    <div className="flex flex-wrap gap-1">
                      {contractor.services_listed.map((c) => <Badge key={c} variant="muted">{c}</Badge>)}
                    </div>
                  ) : null],
                  ["Tier keywords", contractor.specialty_keywords?.length ? (
                    <div className="flex flex-wrap gap-1">
                      {contractor.specialty_keywords.map((k) => <Badge key={k} variant="success">{k}</Badge>)}
                    </div>
                  ) : null],
                  ["Sources", contractor.sources?.length ? (
                    <div className="flex flex-wrap gap-1">
                      {contractor.sources.map((s) => <Badge key={s} variant="muted">{s}</Badge>)}
                    </div>
                  ) : null],
                  ["Years in business", contractor.years_in_business],
                ]}
              />
            </DrawerSection>

            {/* Classification audit trail */}
            <DrawerSection title="Why included" count={classification.data?.length}>
              {classification.isLoading && <div className="text-xs text-muted-foreground">Loading…</div>}
              {classification.data?.length === 0 && (
                <div className="text-xs text-muted-foreground italic">No classification trail recorded.</div>
              )}
              <div className="space-y-2">
                {classification.data?.map((d) => (
                  <div key={d.id} className="rounded border bg-muted/30 p-3 text-xs">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge variant={decisionVariant(d.decision)}>{d.decision}</Badge>
                      {d.assigned_tier && <Badge variant={tierVariant(d.assigned_tier)}>{d.assigned_tier}</Badge>}
                    </div>
                    {d.reason && <div className="mb-1">{d.reason}</div>}
                    {!!d.matched_keywords?.length && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {d.matched_keywords.map((k, i) => (
                          <Badge key={`${k.keyword}-${i}`} variant="success">{k.keyword}</Badge>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </DrawerSection>

            {/* Meta */}
            <DrawerSection title="Meta">
              <DrawerKV
                items={[
                  ["Contractor ID", <code className="text-xs">{contractor.id}</code>],
                  ["Job ID", <code className="text-xs break-all">{contractor.job_id}</code>],
                  ["Place IDs", contractor.place_ids?.length ? (
                    <div className="flex flex-col gap-0.5">
                      {contractor.place_ids.map((p) => <code key={p} className="text-xs break-all">{p}</code>)}
                    </div>
                  ) : null],
                  ["Scraped at", <span className="text-xs"><Calendar className="h-3 w-3 inline mr-1" />{new Date(contractor.scraped_at).toLocaleString()}</span>],
                ]}
              />
            </DrawerSection>
          </DrawerBody>
        </>
      )}
    </Drawer>
  );
}

function Line({ icon, value, children }: { icon: React.ReactNode; value: any; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <span className="text-muted-foreground mt-0.5 shrink-0">{icon}</span>
      <span className="min-w-0 flex-1">{value ? children : <EmptyValue />}</span>
    </div>
  );
}

function RatingCard({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: any; hint?: any }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">{icon}{label}</div>
      <div className="text-lg font-semibold mt-0.5">{value ?? <EmptyValue />}</div>
      {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}
