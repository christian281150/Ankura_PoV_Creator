import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import App from '@/App';

function renderApp() {
  return render(<App />);
}

describe('slot assignment safeguards', () => {
  it('blocks export while assigned blocks have unresolved note-required or blocking flags', () => {
    renderApp();

    expect(screen.getByRole('button', { name: 'Export .pptx' })).toBeDisabled();
    expect(screen.getByText('3 flags unresolved')).toBeInTheDocument();
    expect(screen.getByText('V5')).toBeInTheDocument();
    expect(screen.getByText('V7')).toBeInTheDocument();
  });

  it('renders unavailable blocks with their reason and prevents selection', async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(screen.getByRole('button', { name: /Product grid/ }));

    const unavailable = screen.getByRole('radio', { name: /Segment table/i });
    expect(unavailable).toBeDisabled();
    expect(screen.getByText(/Not disclosed .*no segment split/i)).toBeInTheDocument();
  });

  it('disables a block already assigned in another slot and names that slot', async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(screen.getByRole('button', { name: /Revenue split by geography/ }));

    const revenueSeries = screen.getByRole('radio', { name: /Revenue & EBITDA series/i });
    expect(revenueSeries).toBeDisabled();
    expect(screen.getByText(/already in Top-right/)).toBeInTheDocument();
  });

  it('fails V1 when the revenue basis changes to Gesamtleistung', async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(screen.getByRole('radio', { name: 'Gesamtleistung' }));

    expect(screen.getByRole('heading', { name: /At a glance:.*Gesamtleistung/i })).toBeInTheDocument();
    expect(screen.getByText(/Axis relabelled; export blocked/i)).toBeInTheDocument();
    expect(screen.getByText('V1 fails.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export .pptx' })).toBeDisabled();
  });

  it('adds a written flag note to the preview footnotes', async () => {
    const user = userEvent.setup();
    renderApp();

    const note = 'FY2024 inventory drawdown explained in management commentary.';
    await user.type(
      screen.getByRole('textbox', { name: /Note explaining V5 on Revenue & EBITDA series/i }),
      note,
    );

    expect(screen.getByText(note)).toBeInTheDocument();
  });
});
