import { createContext, useContext, useMemo, useReducer, type ReactNode } from 'react';
import type { ContentBlock, PresentationBasis, ProfileFixture, RuleId, SlotId } from '@/types/profile';
import { SLOT_ORDER } from '@/types/profile';

/**
 * Single reducer for the whole slot-assignment screen. Deliberately no external
 * state library: the state is one object, transitions are few and auditable,
 * and an internal tool does not need the bundle cost.
 */

interface State {
  fixture: ProfileFixture;
  assignment: Record<SlotId, string | null>;
  /** Written notes, keyed `${blockId}:${rule}`. Presence resolves a flag. */
  notes: Record<string, string>;
  revenueBasis: PresentationBasis;
  layoutLocked: boolean;
}

type Action =
  | { type: 'assign'; slot: SlotId; blockId: string }
  | { type: 'note'; blockId: string; rule: RuleId; note: string }
  | { type: 'setBasis'; basis: PresentationBasis }
  | { type: 'resetCanonical' }
  | { type: 'toggleLock' };

function reducer(state: State, action: Action): State {
  if (state.layoutLocked && (action.type === 'assign' || action.type === 'resetCanonical')) {
    return state;
  }
  switch (action.type) {
    case 'assign':
      return { ...state, assignment: { ...state.assignment, [action.slot]: action.blockId } };
    case 'note': {
      const key = `${action.blockId}:${action.rule}`;
      const notes = { ...state.notes };
      if (action.note.trim()) notes[key] = action.note.trim();
      else delete notes[key];
      return { ...state, notes };
    }
    case 'setBasis':
      return { ...state, revenueBasis: action.basis };
    case 'resetCanonical':
      return { ...state, assignment: { ...state.fixture.canonicalLayout } };
    case 'toggleLock':
      return { ...state, layoutLocked: !state.layoutLocked };
  }
}

interface Store extends State {
  dispatch: React.Dispatch<Action>;
  blockById: (id: string | null) => ContentBlock | undefined;
  /** Flags still lacking a note, across the four assigned blocks only. */
  openFlags: { block: ContentBlock; rule: RuleId; severity: string; message: string }[];
  isCanonical: (slot: SlotId) => boolean;
  exportBlocked: boolean;
  footnotes: string[];
}

const Ctx = createContext<Store | null>(null);

export function ProfileProvider({ fixture, children }: { fixture: ProfileFixture; children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, {
    fixture,
    assignment: { ...fixture.canonicalLayout },
    notes: {},
    revenueBasis: 'umsatzerloese',
    layoutLocked: false,
  });

  const value = useMemo<Store>(() => {
    const blockById = (id: string | null) =>
      id ? state.fixture.blocks.find((b) => b.id === id) : undefined;

    const assigned = SLOT_ORDER.map((s) => blockById(state.assignment[s])).filter(
      (b): b is ContentBlock => Boolean(b),
    );

    const openFlags = assigned.flatMap((block) =>
      block.flags
        .filter((f) => f.severity !== 'advisory' && !state.notes[`${block.id}:${f.rule}`])
        .map((f) => ({ block, rule: f.rule, severity: f.severity, message: f.message })),
    );

    // V1: a series labelled "Revenue" must be stated on Umsatzerlöse.
    const basisViolation = state.revenueBasis !== 'umsatzerloese';

    const footnotes = [
      ...assigned.flatMap((b) => b.footnotesAuto),
      ...Object.entries(state.notes).map(([, note]) => note),
    ];

    return {
      ...state,
      dispatch,
      blockById,
      openFlags,
      isCanonical: (slot: SlotId) => state.assignment[slot] === state.fixture.canonicalLayout[slot],
      exportBlocked: openFlags.length > 0 || basisViolation,
      footnotes,
    };
  }, [state]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useProfile(): Store {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useProfile must be used within ProfileProvider');
  return ctx;
}
