/**
 * Domain types for the company profile builder.
 * Mirrors the JSON emitted by the Python normalise layer (AGENTS.md §P2).
 */

export type SlotId = 'top_left' | 'top_right' | 'bottom_left' | 'bottom_right';

export const SLOT_ORDER: SlotId[] = ['top_left', 'top_right', 'bottom_left', 'bottom_right'];

export const SLOT_LABEL: Record<SlotId, string> = {
  top_left: 'Top-left',
  top_right: 'Top-right',
  bottom_left: 'Bottom-left',
  bottom_right: 'Bottom-right',
};

/** §267 HGB size class — determines what disclosure exists at all. */
export type SizeClass = 'klein' | 'mittelgross' | 'gross';

/**
 * The basis a monetary series is stated on. Exists because a series labelled
 * "Revenue" that is actually Gesamtleistung is the failure mode rule V1 catches.
 */
export type PresentationBasis = 'umsatzerloese' | 'gesamtleistung' | 'betriebsleistung' | 'n/a';

export const BASIS_LABEL: Record<PresentationBasis, string> = {
  umsatzerloese: 'Umsatzerlöse',
  gesamtleistung: 'Gesamtleistung',
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

export type RuleId = 'V1' | 'V2' | 'V3' | 'V4' | 'V5' | 'V6' | 'V7' | 'V8' | 'V9';

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
