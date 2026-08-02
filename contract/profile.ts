/**
 * Domain types for the company profile builder.
 * Mirrors the JSON emitted by the Python normalise layer (AGENTS.md Â§P2).
 */

export type SlotId = 'top_left' | 'top_right' | 'bottom_left' | 'bottom_right';

export const SLOT_ORDER: SlotId[] = ['top_left', 'top_right', 'bottom_left', 'bottom_right'];

export const SLOT_LABEL: Record<SlotId, string> = {
  top_left: 'Top-left',
  top_right: 'Top-right',
  bottom_left: 'Bottom-left',
  bottom_right: 'Bottom-right',
};

/** Â§267 HGB size class â€” determines what disclosure exists at all. */
export type SizeClass = 'klein' | 'mittelgross' | 'gross';

/**
 * Reported = as filed. Adjusted = ex management-flagged one-offs.
 * A chart labelled "EBITDA" must state which. See rules.json V11.
 */
export type EarningsBasis = 'reported' | 'adjusted';

export const EARNINGS_BASIS_LABEL: Record<EarningsBasis, string> = {
  reported: 'EBITDA (reported)',
  adjusted: 'EBITDA (adj.)',
};


/**
 * The basis a monetary series is stated on. Exists because a series labelled
 * "Revenue" that is actually Gesamtleistung is the failure mode rule V1 catches.
 */
export type PresentationBasis = 'umsatzerloese' | 'bruttoumsatzerloese' | 'nettoumsatzerloese' | 'gesamtleistung' | 'rohergebnis' | 'betriebsleistung' | 'n/a';

export const BASIS_LABEL: Record<PresentationBasis, string> = {
  umsatzerloese: 'Umsatzerlöse',
  bruttoumsatzerloese: 'Bruttoumsatzerlöse',
  nettoumsatzerloese: 'Nettoumsatzerlöse',
  gesamtleistung: 'Gesamtleistung',
  rohergebnis: 'Rohergebnis',
  betriebsleistung: 'Betriebsleistung',
  'n/a': 'not applicable',
};

export type Confidence = 'high' | 'medium' | 'low';

export interface Provenance {
  doc: string;
  sheet: string;
  row: number;
  page: number | null;
  stdId: string | null;
}

export interface Entity {
  legalName: string;
  register: { court: string; type: 'HRA' | 'HRB'; number: string };
  legalForm: string;
  fiscalYearEnd: string;
  sizeClass: SizeClass;
  filesKonzernabschluss: boolean;
  yearsAvailable: number[];
  confirmedBy: string | null;
  /** Entities that look like the group but are not. Surfaced, never dropped. */
  impostors: { name: string; reason: string }[];
}

export type RuleId = 'V1' | 'V2' | 'V3' | 'V4' | 'V5' | 'V6' | 'V7' | 'V8' | 'V9' | 'V10' | 'V11';

export interface Flag {
  rule: RuleId;
  severity: 'blocking' | 'note_required' | 'advisory';
  message: string;
  /** Analyst-written note. Becomes a slide footnote when present. */
  note: string | null;
}

export type BlockKind =
  | 'bullets'
  | 'chart.column_line'
  | 'chart.stacked_column'
  | 'table'
  | 'map'
  | 'image_grid'
  | 'timeline';

export interface ContentBlock {
  id: string;
  title: string;
  kind: BlockKind;
  eligibleSlots: SlotId[];
  /** 0–1. How complete the underlying data is. */
  coverage: number;
  confidence: Confidence;
  source: string;
  presentationBasis: PresentationBasis;
  earningsBasis?: EarningsBasis;
  framework?: Framework;
  pnlMethod?: PnlMethod;
  /** Non-null => block cannot be selected. Rendered with the reason. */
  unavailableReason: string | null;
  flags: Flag[];
  footnotesAuto: string[];
  provenance: Provenance[];
  series?: { fy: number; value: number }[];
}

export interface CoverageDimension {
  label: string;
  score: number;
}

export interface ProfileFixture {
  entity: Entity;
  blocks: ContentBlock[];
  canonicalLayout: Record<SlotId, string>;
  coverage: CoverageDimension[];
}


/** Accounting framework the figure was reported under. */
export type Framework = 'hgb' | 'ifrs';

/** P&L method. Gesamtkostenverfahren vs Umsatzkostenverfahren. */
export type PnlMethod = 'gkv' | 'ukv';