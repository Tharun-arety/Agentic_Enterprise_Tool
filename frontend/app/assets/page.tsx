"use client";

import { Shell } from "@/components/Shell";
import { DataTable } from "@/components/ui/data-table";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { Ident, Verdict } from "@/components/ui/verdict";
import { formatDate, formatDayOffset, formatTimestamp, daysFromToday } from "@/lib/format";
import { Loaded, useResource } from "@/lib/use-resource";
import { cn } from "@/lib/utils";
import type { AssetBooking, CalibrationRecord } from "@/lib/types";

/**
 * Lab assets.
 *
 * A calibration list exists to answer one question: which rigs may I use, and
 * for how much longer. So the certificate row leads with days remaining rather
 * than with the certificate number, and the soonest expiry sorts first.
 */
export default function LabAssetsPage() {
  const calibration = useResource<CalibrationRecord[]>("/api/assets/calibration");
  const bookings = useResource<AssetBooking[]>("/api/assets/bookings");

  const overdue = calibration.data?.filter((row) => row.overdue).length ?? 0;
  const dueSoon = calibration.data?.filter((row) => row.due_soon).length ?? 0;

  return (
    <Shell
      eyebrow="Quality · instrument register"
      title="Calibration and rig time"
      summary="Which instruments hold a valid certificate, when each lapses, and who has the rigs booked."
      cells={
        calibration.data
          ? [
              { label: "Certificates", value: calibration.data.length },
              {
                label: "Overdue",
                value: <span className={overdue > 0 ? "text-breach" : "text-verified"}>{overdue}</span>,
              },
              {
                label: "Due within 30 days",
                value: <span className={dueSoon > 0 ? "text-warm" : "text-verified"}>{dueSoon}</span>,
              },
            ]
          : []
      }
      onRefresh={() => {
        calibration.reload();
        bookings.reload();
      }}
      refreshing={calibration.refreshing || bookings.refreshing}
    >
      <div className="space-y-4">
        <Panel>
          <PanelHeader
            eyebrow="Calibration"
            title="Certificate validity"
            meta="Soonest expiry first"
          />
          <Loaded resource={calibration}>
            {(rows) => (
              <DataTable
                caption="Calibration certificates and their remaining validity"
                rows={rows}
                rowKey={(row) => row.id}
                emptyTitle="No instruments registered"
                emptyBody="Register a lab asset and record its calibration certificate to see it here."
                columns={[
                  {
                    key: "asset",
                    header: "Instrument",
                    cell: (row) => (
                      <span className="block">
                        <Ident className="font-semibold">{row.asset_tag}</Ident>
                        <span className="text-ink-faint block text-[11px]">{row.asset_name}</span>
                      </span>
                    ),
                  },
                  {
                    key: "remaining",
                    header: "Validity",
                    cell: (row) => {
                      const days = daysFromToday(row.valid_until);
                      return (
                        <span
                          className={cn(
                            "font-semibold",
                            row.overdue ? "text-breach" : row.due_soon ? "text-warm" : "text-verified",
                          )}
                        >
                          {formatDayOffset(days)}
                        </span>
                      );
                    },
                  },
                  {
                    key: "until",
                    header: "Valid until",
                    cell: (row) => <span className="ident">{formatDate(row.valid_until)}</span>,
                  },
                  {
                    key: "calibrated",
                    header: "Calibrated",
                    hideBelow: "sm",
                    cell: (row) => <span className="ident text-ink-dim">{formatDate(row.calibrated_at)}</span>,
                  },
                  {
                    key: "cert",
                    header: "Certificate",
                    hideBelow: "md",
                    cell: (row) => <Ident className="text-ink-dim">{row.certificate_number}</Ident>,
                  },
                  {
                    key: "location",
                    header: "Location",
                    hideBelow: "lg",
                    cell: (row) => <span className="text-ink-dim">{row.location ?? "—"}</span>,
                  },
                  { key: "result", header: "Result", cell: (row) => <Verdict status={row.result} /> },
                ]}
              />
            )}
          </Loaded>
        </Panel>

        <Panel>
          <PanelHeader eyebrow="Rig time" title="Bookings" />
          <Loaded resource={bookings}>
            {(rows) => (
              <DataTable
                caption="Rig bookings"
                rows={rows}
                rowKey={(row) => row.id}
                emptyTitle="No rigs booked"
                emptyBody="Book a rig from the asset register to reserve test time."
                columns={[
                  {
                    key: "asset",
                    header: "Instrument",
                    cell: (row) => (
                      <span className="block">
                        <Ident className="font-semibold">{row.asset_tag}</Ident>
                        <span className="text-ink-faint block text-[11px]">{row.asset_name}</span>
                      </span>
                    ),
                  },
                  { key: "from", header: "From", cell: (row) => <span className="ident">{formatTimestamp(row.starts_at)}</span> },
                  { key: "to", header: "To", hideBelow: "sm", cell: (row) => <span className="ident">{formatTimestamp(row.ends_at)}</span> },
                  { key: "who", header: "Booked by", hideBelow: "md", cell: (row) => row.booked_by ?? "—" },
                  { key: "why", header: "Purpose", hideBelow: "lg", cell: (row) => <span className="text-ink-dim line-clamp-1">{row.purpose}</span> },
                  { key: "status", header: "Status", cell: (row) => <Verdict status={row.status} /> },
                ]}
              />
            )}
          </Loaded>
        </Panel>
      </div>
    </Shell>
  );
}
