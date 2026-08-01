import { useState } from 'react';
import { Badge } from '@/components/ui/Badge';
import { useProfile } from '@/state/profileStore';

const SIZE_NOTE: Record<string, string> = {
  klein: 'Balance sheet only — no P&L filed (§266 Abs. 1)',
  mittelgross: 'Abridged P&L from Rohergebnis — revenue may not be disclosed (§276)',
  gross: 'Full P&L, Lagebericht and §285 Nr. 4 split available',
};

export function EntityBar() {
  const { entity } = useProfile().fixture;
  const [showImpostors, setShowImpostors] = useState(false);
  const reg = `${entity.register.type} ${entity.register.number} · AG ${entity.register.court}`;

  return (
    <header className="border-b border-rule bg-paper-raised">
      <div className="flex items-start gap-6 px-8 py-4">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold text-pine">{entity.legalName}</h1>
          <p className="mt-0.5 font-mono text-micro text-ink-3">
            {reg} · {entity.legalForm} · FYE {entity.fiscalYearEnd} · §267{' '}
            {entity.sizeClass} · {entity.yearsAvailable.length} years filed
          </p>
          <p className="mt-1 text-xs text-ink-2">{SIZE_NOTE[entity.sizeClass]}</p>
        </div>

        <div className="flex shrink-0 items-center gap-3 pt-1">
          {entity.impostors.length > 0 && (
            <button
              type="button"
              onClick={() => setShowImpostors((v) => !v)}
              aria-expanded={showImpostors}
              className="border border-amber-600/40 bg-amber-100 px-2 py-1 font-mono text-micro uppercase tracking-[0.1em] text-amber"
            >
              {entity.impostors.length} near-miss {entity.impostors.length === 1 ? 'entity' : 'entities'}
            </button>
          )}
          <Badge tone="pine">
            Confirmed{entity.confirmedBy ? ` · ${entity.confirmedBy}` : ''}
          </Badge>
        </div>
      </div>

      {showImpostors && (
        <div className="border-t border-rule-hair bg-amber-100/50 px-8 py-3">
          <p className="label-caps mb-2 text-amber">Rejected as group parent</p>
          <ul className="space-y-1">
            {entity.impostors.map((i) => (
              <li key={i.name} className="text-xs text-ink-2">
                <span className="font-mono font-medium text-ink">{i.name}</span> — {i.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </header>
  );
}
