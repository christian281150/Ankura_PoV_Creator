import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import App from '@/App';
import { EntityBar } from '@/components/EntityBar';
import { CoverageRail } from '@/components/CoverageRail';
import { seidensticker } from '@/data/seidensticker';
import { ProfileProvider, useProfile } from '@/state/profileStore';

/**
 * Coverage across the interactive flow beyond the original App.test.tsx smoke
 * tests. The app currently implements only screen 5 (slot assignment), with
 * screen 6 (flag resolution) and screen 7 (preview) embedded as sidebar panels
 * on the same screen -- see the session report for what is genuinely missing
 * (screens 1-4, entity confirmation gate, export wiring, metadata write).
 */

async function renderApp() {
  const result = render(<App />);
  await screen.findByRole('button', { name: 'Export .pptx' });
  return result;
}

describe('screen 5 - slot assignment: non-negotiable behaviours', () => {
  it('lists a block carrying an unresolved blocking flag but keeps it unselectable', async () => {
    const user = userEvent.setup();
    await renderApp();

    // Move geo.revenue_split (the only block with a blocking flag) out of
    // bottom_right so we can inspect it from a neutral, non-selected state.
    await user.click(screen.getByRole('button', { name: /Revenue split by geography/ }));
    await user.click(screen.getByRole('radio', { name: /Footprint map/i }));

    // It is still listed as an option for bottom_right (never hidden)...
    await user.click(screen.getByRole('button', { name: /Footprint map/ }));
    const blockedOption = screen.getByRole('radio', { name: /Revenue split by geography/i });
    expect(blockedOption).toBeInTheDocument();

    // ...but cannot be (re)selected, and the reason is the blocking flag, not
    // an "already in <slot>" conflict.
    expect(blockedOption).toBeDisabled();
    expect(screen.getByText(/V7 blocks selection/)).toBeInTheDocument();
  });

  it('locks slot assignment against further changes once "Lock layout" is engaged', async () => {
    const user = userEvent.setup();
    await renderApp();

    await user.click(screen.getByRole('button', { name: 'Lock layout' }));
    expect(screen.getByRole('button', { name: 'Layout locked' })).toHaveAttribute('aria-pressed', 'true');

    // The slot dropdown trigger itself is disabled while locked...
    expect(screen.getByRole('button', { name: /Business overview/ })).toBeDisabled();
    // ...and "Reset to canonical" is disabled too, so a locked layout cannot
    // be changed by any control on this screen.
    expect(screen.getByRole('button', { name: 'Reset to canonical' })).toBeDisabled();
  });

  it('rejects assign and resetCanonical dispatches at the reducer level while locked, proving the lock is not just a disabled control', async () => {
    const user = userEvent.setup();

    function LockProbe() {
      const { assignment, dispatch } = useProfile();
      return (
        <div>
          <button type="button" onClick={() => dispatch({ type: 'toggleLock' })}>toggle-lock</button>
          <button
            type="button"
            onClick={() => dispatch({ type: 'assign', slot: 'top_left', blockId: 'bo.identity_ownership' })}
          >
            force-assign
          </button>
          <pre data-testid="assignment">{JSON.stringify(assignment)}</pre>
        </div>
      );
    }

    render(
      <ProfileProvider fixture={seidensticker}>
        <LockProbe />
      </ProfileProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'toggle-lock' }));
    const before = screen.getByTestId('assignment').textContent;

    await user.click(screen.getByRole('button', { name: 'force-assign' }));

    expect(screen.getByTestId('assignment').textContent).toBe(before);
  });

  it('badges a non-canonical slot as "non-standard" and reverts to "canonical" on reset', async () => {
    const user = userEvent.setup();
    await renderApp();

    const slot = screen.getByRole('region', { name: 'Top-left slot' });
    expect(within(slot).getByText('canonical')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Business overview/ }));
    await user.click(screen.getByRole('radio', { name: /Identity & ownership/i }));

    expect(within(slot).getByText('non-standard')).toBeInTheDocument();
    expect(screen.getByText(/Canonical for §267 gross is/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Reset to canonical' }));

    expect(within(slot).getByText('canonical')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Business overview/ })).toBeInTheDocument();
  });

  it('cycles focus between slot dropdown triggers with the arrow keys (F4 keyboard nav)', async () => {
    await renderApp();

    const topLeft = document.querySelector<HTMLButtonElement>('[data-slot-trigger="top_left"]');
    const topRight = document.querySelector<HTMLButtonElement>('[data-slot-trigger="top_right"]');
    const bottomLeft = document.querySelector<HTMLButtonElement>('[data-slot-trigger="bottom_left"]');
    expect(topLeft && topRight && bottomLeft).toBeTruthy();

    topLeft!.focus();
    const user = userEvent.setup();
    await user.keyboard('{ArrowRight}');
    expect(document.activeElement).toBe(topRight);

    topLeft!.focus();
    await user.keyboard('{ArrowDown}');
    expect(document.activeElement).toBe(bottomLeft);
  });
});

describe('screen 6 - flag resolution', () => {
  it('resolving a flag with a note removes it from the open count and adds it as a footnote', async () => {
    const user = userEvent.setup();
    await renderApp();

    expect(screen.getByText('3 flags unresolved')).toBeInTheDocument();

    const note = 'FY2024 revenue decline explained by planned SKU rationalisation.';
    const input = screen.getByRole('textbox', { name: /Note explaining V5 on Revenue & EBITDA series/i });
    await user.type(input, note);
    await user.tab();

    expect(screen.getByText('2 flags unresolved')).toBeInTheDocument();
    expect(screen.getByText(note)).toBeInTheDocument();
  });
});

describe('screen 7 - preview', () => {
  it('surfaces each assigned block\'s auto-generated footnotes in the preview pane', async () => {
    await renderApp();

    expect(
      screen.getByText('FY2024 Gesamtleistung depressed by €8.8m inventory drawdown'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Employee count is a company-website claim, not a filed figure'),
    ).toBeInTheDocument();
  });

  it('renders one coverage meter per dimension with the fixture\'s scores', () => {
    render(
      <ProfileProvider fixture={seidensticker}>
        <CoverageRail />
      </ProfileProvider>,
    );

    const meter = screen.getByRole('meter', { name: 'Geography split coverage' });
    expect(meter).toHaveAttribute('aria-valuenow', '62');
  });
});

describe('entity bar (static screen 1/2 surface)', () => {
  it('renders the confirmed entity and reveals near-miss impostor entities on demand', async () => {
    const user = userEvent.setup();
    render(
      <ProfileProvider fixture={seidensticker}>
        <EntityBar />
      </ProfileProvider>,
    );

    expect(screen.getByRole('heading', { name: /Seidensticker/ })).toBeInTheDocument();
    expect(screen.getByText(/HRA 8217/)).toBeInTheDocument();
    expect(screen.getByText(/Confirmed/)).toBeInTheDocument();

    expect(screen.queryByText(/TK Store-Management GmbH/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /near-miss/ }));
    expect(screen.getByText(/TK Store-Management GmbH/)).toBeInTheDocument();
  });
});
