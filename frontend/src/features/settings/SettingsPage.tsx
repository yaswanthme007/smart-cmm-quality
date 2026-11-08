import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/client'
import type { Settings, Severity } from '../../api/types'
import { Button, Card, ErrorBox, Field, inputClass, PageHeader } from '../../components/ui'

const RULES = ['N1', 'N2', 'N3', 'N4', 'N5', 'N6', 'N7', 'N8']
const SEVERITIES: Severity[] = ['CRITICAL', 'SIGNIFICANT', 'STANDARD']

export function SettingsPage() {
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api.get<Settings>('/settings') })
  if (!settings.data) return <div className="text-slate-500">Loading…</div>
  return <SettingsForm key={JSON.stringify(settings.data)} initial={settings.data} />
}

function SettingsForm({ initial }: { initial: Settings }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Settings>(initial)
  const [sound, setSound] = useState(() => localStorage.getItem('alertSound') !== 'off')
  const save = useMutation({
    mutationFn: (s: Settings) =>
      api.put<Settings>('/settings', {
        guard_band_pct_default: s.guard_band_pct_default,
        escalation: s.escalation,
        spc_rules_enabled: s.spc_rules_enabled,
        recurrence_window_hours: s.recurrence_window_hours,
        uncertainty_rule_enabled: s.uncertainty_rule_enabled,
        ai_enabled: s.ai_enabled,
      }),
    onSuccess: (data) => queryClient.setQueryData(['settings'], data),
  })
  const timers = draft.escalation.timers

  const setTimer = (profile: 'demo' | 'plant', sev: Severity, level: 0 | 1, minutes: number) => {
    const pair = [...timers[profile][sev]] as [number, number]
    pair[level] = Math.round(minutes * 60)
    setDraft({ ...draft, escalation: { ...draft.escalation, timers: { ...timers, [profile]: { ...timers[profile], [sev]: pair } } } })
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Settings" subtitle="Defaults set by the plant. Every change is written to the audit log." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Classification">
          <Field label="Default guard band (% of tolerance width)" hint="Marginal = in tolerance but closer than this to a limit. Per-characteristic overrides in Masters.">
            <input type="number" min={0} max={50} className={inputClass} value={draft.guard_band_pct_default} onChange={(e) => setDraft({ ...draft, guard_band_pct_default: Number(e.target.value) })} />
          </Field>
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={draft.uncertainty_rule_enabled} onChange={(e) => setDraft({ ...draft, uncertainty_rule_enabled: e.target.checked })} />
            Uncertainty-aware decision rule (ISO 14253-1 idea; uses each characteristic's expanded uncertainty)
          </label>
          <Field label="Recurrence window (hours)" hint="A Not OK on the same part + machine + characteristic within this window links to the open NC.">
            <input type="number" min={1} max={168} className={inputClass} value={draft.recurrence_window_hours} onChange={(e) => setDraft({ ...draft, recurrence_window_hours: Number(e.target.value) })} />
          </Field>
        </Card>
        <Card title="Escalation timers">
          <div className="mb-3 flex gap-2">
            {(['demo', 'plant'] as const).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setDraft({ ...draft, escalation: { ...draft.escalation, profile: p } })}
                className={`min-h-10 rounded-md px-3 py-2 text-sm ${draft.escalation.profile === p ? 'bg-slate-900 text-white' : 'border border-slate-300'}`}
              >
                {p === 'demo' ? 'Demo profile (seconds)' : 'Plant profile'}
              </button>
            ))}
          </div>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500 uppercase">
              <tr>
                <th>Class</th>
                <th>L1 → Supervisor (min)</th>
                <th>L2 → Quality Head (min)</th>
              </tr>
            </thead>
            <tbody>
              {SEVERITIES.map((sev) => (
                <tr key={sev}>
                  <td className="py-1 font-medium">{sev}</td>
                  {([0, 1] as const).map((lvl) => (
                    <td key={lvl} className="pr-2">
                      <input
                        type="number"
                        step="0.5"
                        min={0.5}
                        className={inputClass}
                        value={timers[draft.escalation.profile][sev][lvl] / 60}
                        onChange={(e) => setTimer(draft.escalation.profile, sev, lvl, Number(e.target.value))}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-500">Demo timers are shortened for the video (60 s / 120 s). Escalation stops when the owner acknowledges.</p>
        </Card>
        <Card title="SPC rules (Nelson)">
          <div className="flex flex-wrap gap-3">
            {RULES.map((r) => (
              <label key={r} className="flex items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  checked={draft.spc_rules_enabled.includes(r)}
                  onChange={(e) =>
                    setDraft({ ...draft, spc_rules_enabled: e.target.checked ? [...draft.spc_rules_enabled, r].sort() : draft.spc_rules_enabled.filter((x) => x !== r) })
                  }
                />
                {r}
              </label>
            ))}
          </div>
          <p className="mt-2 text-xs text-slate-500">Default N1, N2, N3, N5. Each extra rule raises the false-alarm rate.</p>
        </Card>
        <Card title="Optional AI and this browser">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" disabled={!draft.ai_available} checked={draft.ai_enabled} onChange={(e) => setDraft({ ...draft, ai_enabled: e.target.checked })} />
            AI assistance (PDF extraction with confirmation, similar past NCs){!draft.ai_available && ' (AI_ENABLED=false on the server)'}
          </label>
          <p className="mt-1 text-xs text-slate-500">AI never classifies, alerts or escalates; the core loop is deterministic.</p>
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={sound}
              onChange={(e) => {
                setSound(e.target.checked)
                localStorage.setItem('alertSound', e.target.checked ? 'on' : 'off')
              }}
            />
            Play a sound on new alerts (this browser)
          </label>
        </Card>
      </div>
      <ErrorBox error={save.error} />
      <div className="flex gap-2">
        <Button onClick={() => save.mutate(draft)} disabled={save.isPending}>
          Save settings
        </Button>
        {save.isSuccess && <span className="self-center text-sm text-green-700">Saved and audited.</span>}
      </div>
    </div>
  )
}
