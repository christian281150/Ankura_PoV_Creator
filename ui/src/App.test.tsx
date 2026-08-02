import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import App from '@/App';
import { seidensticker } from '@/data/seidensticker';
import { ActionBar } from '@/components/ActionBar';
import { BasisGuard } from '@/components/BasisGuard';
import { ProfileProvider } from '@/state/profileStore';

async function renderApp() {
  const result = render(<App />);
  await screen.findByRole('button', { name: 'Export .pptx' });
  return result;
}

describe('slot assignment safeguards', () => {
  it('blocks export while assigned blocks have unresolved note-required or blocking flags', async () => {
    await renderApp();

    expect(screen.getByRole('button', { name: 'Export .pptx' })).toBeDisabled();
    expect(screen.getByText('3 flags unresolved')).toBeInTheDocument();
    expect(screen.getByText('V5')).toBeInTheDocument();
    expect(screen.getByText('V7')).toBeInTheDocument();
  });

  it('renders unavailable blocks with their reason and prevents selection', async () => {
    const user = userEvent.setup();
    await renderApp();

    await user.click(screen.getByRole('button', { name: /Product grid/ }));

    const unavailable = screen.getByRole('radio', { name: /Segment table/i });
    expect(unavailable).toBeDisabled();
    expect(screen.getByText(/Not disclosed .*no segment split/i)).toBeInTheDocument();
  });

  it('disables a block already assigned in another slot and names that slot', async () => {
    const user = userEvent.setup();
    await renderApp();

    await user.click(screen.getByRole('button', { name: /Revenue split by geography/ }));

    const revenueSeries = screen.getByRole('radio', { name: /Revenue & EBITDA series/i });
    expect(revenueSeries).toBeDisabled();
    expect(screen.getByText(/already in Top-right/)).toBeInTheDocument();
  });

  it('fails V1 when the revenue basis changes to Gesamtleistung', async () => {
    const user = userEvent.setup();
    await renderApp();

    await user.click(screen.getByRole('radio', { name: 'Gesamtleistung' }));

    expect(screen.getByRole('heading', { name: /At a glance:.*Gesamtleistung/i })).toBeInTheDocument();
    expect(screen.getByText(/Axis relabelled; export blocked/i)).toBeInTheDocument();
    expect(screen.getByText('V1 fails.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export .pptx' })).toBeDisabled();
  });

  it('does not allow adjusted EBITDA without management-stated adjustments', async () => {
    const user = userEvent.setup();
    await renderApp();

    const adjusted = screen.getByRole('radio', { name: 'EBITDA (adj.)' });
    expect(adjusted).toBeDisabled();
    expect(screen.getByText('⊘ no management-stated adjustments available')).toBeInTheDocument();
    await user.click(adjusted);
    expect(screen.getByRole('radio', { name: 'EBITDA (reported)' })).toBeChecked();
  });

  it('blocks export under V11 if invalid adjusted data reaches the UI', () => {
    const invalidAdjustedFixture = {
      ...seidensticker,
      blocks: seidensticker.blocks.map((block) => ({
        ...block,
        flags: [],
        ...(block.id === 'fin.revenue_ebitda_series' ? { earningsBasis: 'adjusted' as const } : {}),
      })),
    };

    render(
      <ProfileProvider fixture={invalidAdjustedFixture}>
        <BasisGuard />
        <ActionBar />
      </ProfileProvider>,
    );

    expect(screen.getByRole('button', { name: 'Export .pptx' })).toBeDisabled();
    expect(screen.getByText('earnings basis fails V11')).toBeInTheDocument();
  });

  it('adds a written flag note to the preview footnotes', async () => {
    const user = userEvent.setup();
    await renderApp();

    const note = 'FY2024 inventory drawdown explained in management commentary.';
    await user.type(
      screen.getByRole('textbox', { name: /Note explaining V5 on Revenue & EBITDA series/i }),
      note,
    );

    expect(screen.getByText(note)).toBeInTheDocument();
  });
});
