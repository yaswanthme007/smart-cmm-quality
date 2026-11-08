export type Role = 'ADMIN' | 'QUALITY_HEAD' | 'SUPERVISOR' | 'PROCESS_OWNER' | 'INSPECTOR' | 'VIEWER'
export type Result = 'OK' | 'MARGINAL' | 'NOK'
export type NcStatus = 'OPEN' | 'ACKNOWLEDGED' | 'IN_PROGRESS' | 'PENDING_VERIFICATION' | 'CLOSED' | 'CANCELLED'
export type Severity = 'CRITICAL' | 'SIGNIFICANT' | 'STANDARD'

export interface User {
  id: string
  email: string
  full_name: string
  role: Role
  department_id: string | null
}

export interface Warning {
  code: string
  message: string
  char_no?: string
}

export interface Measurement {
  id: string
  characteristic_id: string | null
  char_no: string
  char_name: string | null
  actual: string
  nominal: string | null
  usl: string | null
  lsl: string | null
  deviation: string | null
  tolerance_used_pct: string | null
  result: Result
  is_suspect: boolean
  limits_source: 'MASTER' | 'REPORT'
  classification: Severity | null
  tolerance_type: string | null
}

export interface Report {
  id: string
  report_no: string
  part_id: string | null
  part_no: string | null
  part_name: string | null
  machine_id: string | null
  machine_code: string | null
  process_code: string | null
  cmm_code: string | null
  serial_no: string | null
  operator_name: string | null
  measured_at: string | null
  received_at: string
  ingested_at: string | null
  source: string
  original_filename: string | null
  part_result: Result | null
  nok_count: number
  marginal_count: number
  status: 'INGESTED' | 'NEEDS_CONFIRMATION' | 'FAILED'
  warnings: Warning[]
  reinspection_of_report_id: string | null
}

export interface ReportDetail extends Report {
  measurements: Measurement[]
  nc_ids: string[]
  nc_nos: string[]
  reinspected_by: string[]
  errors?: string[]
}

export interface Page<T> {
  total: number
  items: T[]
}

export interface Nc {
  id: string
  nc_no: string
  part_no: string | null
  part_name: string | null
  machine_code: string | null
  process_code: string | null
  first_report_id: string
  severity: Severity
  status: NcStatus
  owner_user_id: string | null
  owner_name: string | null
  supervisor_name: string | null
  detected_at: string
  acknowledged_at: string | null
  escalation_level: number
  target_date: string | null
  containment: string | null
  root_cause_category: string | null
  root_cause: string | null
  corrective_action: string | null
  preventive_action: string | null
  submitted_at: string | null
  verified_at: string | null
  verification_note: string | null
  closed_at: string | null
  cancel_reason: string | null
  recurrence_count: number
  warnings: Warning[]
  overdue: boolean
  age_hours: number
  characteristics: string[]
  can_work: boolean
}

export interface NcMeasurement {
  id: string
  report_id: string
  report_no: string
  serial_no: string | null
  char_no: string
  char_name: string | null
  actual: string
  nominal: string | null
  usl: string | null
  lsl: string | null
  deviation: string | null
  result: Result
  is_suspect: boolean
  measured_at: string | null
  classification: Severity | null
}

export interface Evidence {
  id: string
  filename: string
  mime: string
  size: number
  note: string | null
  created_at: string
}

export interface NcDetail extends Nc {
  measurements: NcMeasurement[]
  evidence: Evidence[]
  reinspection_ok_report: { id: string; report_no: string; part_result: Result; received_at: string } | null
}

export interface TimelineEvent {
  at: string
  kind: string
  title: string
  detail: string | null
  actor: string | null
  ms: number | null
}

export interface Alert {
  id: string
  kind: 'NOK' | 'RECURRENCE' | 'ESCALATION' | 'SPC_WARNING' | 'SYSTEM'
  nc_id: string | null
  nc_no: string | null
  spc_signal_id: string | null
  level: number
  title: string
  body: string
  recipient_name: string | null
  created_at: string
  read_at: string | null
  acknowledged_at: string | null
  generation_ms: number | null
}

export interface AlertPage extends Page<Alert> {
  unread: number
}

export interface KpiSummary {
  k1: { inspected: number; ok: number; ok_only: number; marginal: number; nok: number }
  k2: {
    ok_pct: number | null
    nok_pct: number | null
    marginal_pct: number | null
    characteristics_measured: number
    characteristics_nok: number
    characteristic_nok_pct: number | null
  }
  k3: {
    count: number
    median_ms: number | null
    p95_ms: number | null
    max_ms: number | null
    email_count: number
    email_median_ms: number | null
    email_p95_ms: number | null
  }
  k3b: { count: number; median_s: number | null; p95_s: number | null }
  k4: { open: number; pending: number; closed: number; cancelled: number; overdue: number; escalated_open: number }
  k5: {
    closed_count: number
    median_h: number | null
    p90_h: number | null
    closed_on_time_pct: number | null
    ack_median_min: number | null
  }
  ageing: { bucket: string; count: number }[]
  generated_at: string
}

export interface TrendPoint {
  bucket: string
  group: string | null
  inspected: number
  nok: number
  marginal: number
  nok_pct: number | null
}

export interface ParetoRow {
  part_no: string
  char_no: string
  name: string | null
  label: string
  count: number
  cumulative_pct: number | null
}

export interface ByRow {
  group: string
  id: string
  inspected: number
  nok: number
  nok_pct: number | null
}

export interface MasterRow {
  id: string
  [key: string]: unknown
}

export interface MappingProfile {
  id?: string
  name: string
  vendor: string
  file_kind: 'CSV' | 'XLSX' | 'TSV' | 'CALYPSO_CHR' | 'AQDEF' | 'PDF'
  delimiter: string | null
  decimal_separator: string
  header_row: number
  column_map: Record<string, string>
  header_fields: Record<string, { from: string; regex?: string; column?: string; value?: string }>
  unit: string
  is_active: boolean
}

export interface PreviewOut {
  detected_kind: string
  columns: string[]
  sample: (string | null)[][]
  header: Record<string, string | null>
  rows: {
    char_no: string
    char_name: string | null
    actual: string
    nominal: string | null
    usl: string | null
    lsl: string | null
    result: Result | null
    limits_source: string
  }[]
  error: string | null
  canonical_fields: string[]
}

export interface SpcStream {
  characteristic_id: string
  char_no: string
  name: string
  part_no: string
  machine_id: string
  machine_code: string
  points: number
  active_signals: string[]
}

export interface SpcChart {
  characteristic: {
    id: string
    char_no: string
    name: string
    part_no: string
    classification: Severity
    tolerance_type: string
    nominal: number | null
    usl: number | null
    lsl: number | null
    decimals: number
  }
  points: { id: string; report_id: string; measured_at: string | null; value: number; mr: number | null; result: Result; is_suspect: boolean }[]
  limits: {
    center: number
    ucl: number
    lcl: number
    mr_bar: number
    ucl_mr: number
    sigma_within: number
    n_baseline: number
    baseline_from: string | null
    baseline_to: string | null
  } | null
  signals: { id: string; rule: string; description: string; status: string; triggered_at: string }[]
  marks: { rule: string; index: number; measurement_id: string }[]
  capability: { valid: boolean; message: string | null; n: number; cp: number | null; cpk: number | null; pp: number | null; ppk: number | null }
}

export interface AuditEntry {
  id: number
  at: string
  actor_name: string | null
  actor_role: string | null
  action: string
  entity: string
  entity_id: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  request_id: string | null
  ip: string | null
}

export interface Settings {
  guard_band_pct_default: number
  escalation: {
    profile: 'demo' | 'plant'
    timers: Record<'demo' | 'plant', Record<Severity, [number, number]>>
    recurrence_escalate_at: number
  }
  spc_rules_enabled: string[]
  recurrence_window_hours: number
  ai_enabled: boolean
  uncertainty_rule_enabled: boolean
  shifts: { timezone: string; list: { name: string; start: string }[] }
  ai_available: boolean
  demo_mode: boolean
}

export interface Filters {
  date_from?: string
  date_to?: string
  part_id?: string
  machine_id?: string
  process_id?: string
  shift?: string
}
