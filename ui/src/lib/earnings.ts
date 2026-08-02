import type { ContentBlock, Provenance } from '@/types/profile';

/** Validated at the UI boundary until the contract exposes adjustments. */
export interface EarningsAdjustment {
  amount: number;
  description: string;
  provenance: Provenance;
}

type BlockWithAdjustments = ContentBlock & { adjustments?: unknown };

function isProvenance(value: unknown): value is Provenance {
  if (!value || typeof value !== 'object') return false;
  const provenance = value as Record<string, unknown>;
  return typeof provenance.doc === 'string' && provenance.doc.trim().length > 0
    && typeof provenance.sheet === 'string' && provenance.sheet.trim().length > 0
    && typeof provenance.row === 'number' && Number.isFinite(provenance.row)
    && (typeof provenance.page === 'number' || provenance.page === null)
    && (typeof provenance.stdId === 'string' || provenance.stdId === null);
}

function isAdjustment(value: unknown): value is EarningsAdjustment {
  if (!value || typeof value !== 'object') return false;
  const adjustment = value as Record<string, unknown>;
  return typeof adjustment.amount === 'number' && Number.isFinite(adjustment.amount)
    && typeof adjustment.description === 'string' && adjustment.description.trim().length > 0
    && isProvenance(adjustment.provenance);
}

/** Returns null unless every declared adjustment is fully auditable. */
export function validatedAdjustments(block: ContentBlock | undefined): EarningsAdjustment[] | null {
  const adjustments = (block as BlockWithAdjustments | undefined)?.adjustments;
  return Array.isArray(adjustments) && adjustments.length > 0 && adjustments.every(isAdjustment)
    ? adjustments
    : null;
}

export function adjustmentReconciliation(adjustments: EarningsAdjustment[]): string {
  const total = adjustments.reduce((sum, adjustment) => sum + adjustment.amount, 0);
  const amount = `€${(total / 1_000_000).toFixed(1)}m`;
  const detail = adjustments
    .map((adjustment) => `${adjustment.description} (${adjustment.provenance.doc}, ${adjustment.provenance.sheet}, row ${adjustment.provenance.row})`)
    .join('; ');
  return `EBITDA reconciliation: EBITDA (reported) + ${amount} management-stated adjustments = EBITDA (adj.). ${detail}`;
}
