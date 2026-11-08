/** KPI definitions shown as tooltips (Section 13, docs/KPI_DEFINITIONS.md). */
export const KPI_HINTS = {
  K1: 'K1: count of inspection reports (parts) in the period. OK = OK + Marginal; Not OK = part result Not OK.',
  K2: 'K2: OK ÷ Inspected × 100 and Not OK ÷ Inspected × 100, one decimal.',
  K3: 'K3: per Not OK result, alert created_at − report received_at. Median, p95, max; every value in the list.',
  K4: 'K4: Open = Open + Acknowledged; Pending = In progress + Pending verification; Closed. Cancelled and Overdue separate.',
  K5: 'K5: closure lead time closed_at − detected_at (median, p90); acknowledgement time acknowledged_at − detected_at.',
}
