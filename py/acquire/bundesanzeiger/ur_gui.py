"""
ur_gui.py  —  Desktop GUI for the Unternehmensregister Financial Extractor
===========================================================================
Phase 3: Multi-company session model, outer/inner tab strip, All Tables view
with reclassify context menu, status-bar chips, and tokens.py design system.

Architecture overview
---------------------
  GUI thread (Tkinter / CustomTkinter main thread)
    • Three-zone layout: status track | left rail | center canvas | right rail
    • Left rail: 240px company switcher
    • Center canvas: outer tabs (OVERVIEW / All Tables) + inner tabs (Bilanz/GuV/Cashflow)
    • Right rail is collapsible: audit drawer or needs-review list
    • All widget access from main thread only (CTk rule)

  Worker thread (asyncio / Playwright background thread)
    • Queue-based communication via _gui_q (worker→GUI) and _cmd_q (GUI→worker)
    • GUI polls _gui_q every 100 ms via self.after(100, self._poll)

Event contract (worker → GUI queue)
  ready               ()
  status              str
  search_results      list[dict] | None
  need_confirm        None
  batch_progress      (float, str)
  batch_doc_done      (doc_dict, tables)    doc_dict includes pdf_path
  batch_error         (idx, label, msg)
  batch_complete      None
  overview_ready      (company_id, overview_tables)
  bundle_written      (ok, path_str)
  exported            (count, Path)
  error               str

Command contract (GUI → worker queue)
  search              company_name: str
  process_batch       (docs, pdf_root)
  recompute_overview  (company_id, all_tables, bundle_info, row_merges)
  export_v2           (ov_tables, all_tables, result, path, dec, tho, pdf_dir, review_meta)
  navigate_home       None
  quit                None
"""

import asyncio
import csv
import datetime
import io
import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import customtkinter as ctk

from tokens import T, FONT, SPACE, ROW_H, RADIUS, BORDER, BADGE, LAYOUT

# ── Per-user preferences ──────────────────────────────────────────────────────
_PREFS_PATH   = Path.home() / "Downloads" / "UR_Extracts" / "prefs.json"
_ALIASES_PATH = Path(__file__).parent / "aliases" / "client_aliases.csv"


def _load_user_prefs() -> dict:
    """Load persisted user preferences from the prefs JSON (empty dict if absent)."""
    try:
        return json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_user_prefs(prefs: dict) -> None:
    """Persist the user-preferences dict to the prefs JSON. Best-effort."""
    try:
        _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PREFS_PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except Exception:
        pass


_USER_PREFS: dict = _load_user_prefs()

# ── Stdout capture (installed BEFORE ur_extractor so Rich Console captures it)
_LOG_Q:    queue.Queue = queue.Queue(maxsize=2000)
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[mGKHFABCDJK]')
_PREVIEW_NUM_RE = re.compile(r'\d{1,3}(?:\.\d{3})+|\d+,\d+')


class _SessionLogger:
    """Per-user per-session log file in ~/Downloads/UR_Extracts/logs/."""

    def __init__(self):
        """Resolve the log directory and open the timestamped session log file."""
        self._fh              = None
        self._lock            = threading.Lock()
        self.log_path         = None
        self._delete_on_close = _USER_PREFS.get("log_delete_on_close", False)
        _default_log = str(Path.home() / "Downloads" / "UR_Extracts" / "logs")
        log_dir = Path(_USER_PREFS.get("log_dir", _default_log)).expanduser()
        self._open_log_file(log_dir)

    def _open_log_file(self, log_dir: Path = None):
        """Create the log directory and open the timestamped session log for writing."""
        try:
            if log_dir is None:
                log_dir = Path.home() / "Downloads" / "UR_Extracts" / "logs"
            username  = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
            hostname  = socket.gethostname()
            now       = datetime.datetime.now()
            timestamp = now.strftime("%Y%m%d_%H%M%S")
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path      = log_dir / f"UR_{username}_{timestamp}.log"
            self.log_path = log_path
            self._fh      = open(log_path, "w", encoding="utf-8", buffering=1)
            exe_path = sys.executable if getattr(sys, "frozen", False) else __file__
            header = (
                f"{'='*60}\n"
                f"  UR Financial Extractor — Session Log\n"
                f"  Started : {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"  User    : {username}\n"
                f"  Host    : {hostname}\n"
                f"  Exe     : {exe_path}\n"
                f"  Log     : {log_path}\n"
                f"{'='*60}\n"
            )
            self._fh.write(header)
            self._fh.flush()
        except Exception:
            self._fh = None

    def write_line(self, line: str):
        """Append one timestamped line to the session log."""
        if not self._fh:
            return
        try:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            with self._lock:
                self._fh.write(f"[{ts}] {line}\n")
        except Exception:
            pass

    def close(self):
        """Flush and close the session log; optionally delete it per user setting."""
        try:
            if self._fh:
                self._fh.write(
                    f"\n{'='*60}\n  Session ended: "
                    f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"{'='*60}\n")
                self._fh.close()
            if self._delete_on_close and self.log_path and self.log_path.exists():
                self.log_path.unlink()
        except Exception:
            pass


_SESSION_LOG = _SessionLogger()


class _LogCapture:
    """Transparent stdout proxy — captures Rich output before ur_extractor import."""

    def __init__(self, orig):
        """Wrap a stream so writes are mirrored into the session log."""
        self._orig = orig
        self._buf  = ""

    def write(self, text: str) -> int:
        """Mirror written text to the underlying stream and into the session log."""
        if self._orig:
            try:
                self._orig.write(text)
            except Exception:
                pass
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            clean = _ANSI_RE.sub("", line).strip()
            if clean:
                try:
                    _LOG_Q.put_nowait(clean)
                except queue.Full:
                    pass
                _SESSION_LOG.write_line(clean)
        return len(text)

    def flush(self):
        """Flush the wrapped stream."""
        if self._orig:
            try:
                self._orig.flush()
            except Exception:
                pass

    def isatty(self):
        """Proxy isatty() to the wrapped stream (keeps rich/console output happy)."""
        return False

    def __getattr__(self, name):
        """Delegate any other attribute access to the wrapped stream."""
        return getattr(self._orig, name)


sys.stdout = _LogCapture(sys.__stdout__)

from ur_extractor import (
    BASE_URL, PAGE_LOAD_TIMEOUT,
    launch_browser, run_search,
    open_document, download_pdf,
    extract_tables_from_pdf, export_to_excel, export_to_excel_v2,
    build_multi_year_tables,
    sanitize_filename, _minimize_all_browsers,
    _get_browser_hwnds, _hide_hwnds, _minimize_hwnds, _classify_table,
    effective_table_type,
    load_table_overrides, save_table_override, apply_table_overrides,
    write_feedback_bundle, _normalize_for_override_key, _OVERRIDES_PATH,
    make_override_record, override_filing_id,
    load_row_merges, save_row_merge, clear_row_merges,
    save_company_to_library, list_library_entries, load_library_company,
    delete_library_entry, library_dir,
    prepare_library_save, write_library_file,
)

# ── HGB canonical map (optional — degrades gracefully when absent) ─────────────
try:
    sys.path.insert(0, str(Path(__file__).parent / "lib"))
    import lib.hgb_map as _hgb
    _HGB_AVAILABLE = True
except Exception:
    _HGB_AVAILABLE = False

# ── Config (non-color values only) ────────────────────────────────────────────
from config import (
    WINDOW_WIDTH, WINDOW_HEIGHT, WINDOW_MIN_W, WINDOW_MIN_H,
    CURRENCY_UNITS, DEFAULT_CURRENCY, DEFAULT_THEME,
)

# ── Font aliases (from tokens.py) ─────────────────────────────────────────────
_SANS  = FONT["family_sans"]
F_H1   = FONT["small_bold"]
F_H2   = FONT["small_bold"]
F_BODY = FONT["body"]
F_SM   = FONT["small"]
F_XS   = FONT["caption"]
F_MONO = FONT["num_small"]
F_LABEL = (_SANS, 9, "bold")

# ── Radius aliases ────────────────────────────────────────────────────────────
R_PILL = RADIUS["lg"]
R_CARD = RADIUS["md"]
R_SM   = RADIUS["sm"]

# ── Statement type constants ───────────────────────────────────────────────────
_STMT_NAMES  = {0: "Bilanz", 1: "GuV", 2: "Cashflow"}
_TYPE_LABELS = {0: "Bilanz", 1: "GuV", 2: "Cashflow", 99: "Other"}


# ── Module-level helpers ───────────────────────────────────────────────────────

def _tint(hex_color: str, alpha: float = 0.20,
          bg: tuple = (0x13, 0x13, 0x1f)) -> str:
    """Return a lightened/blended variant of a hex colour (UI tinting helper)."""
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    nr = int(r * alpha + bg[0] * (1 - alpha))
    ng = int(g * alpha + bg[1] * (1 - alpha))
    nb = int(b * alpha + bg[2] * (1 - alpha))
    return f"#{nr:02x}{ng:02x}{nb:02x}"


def _short_heading(t: dict) -> str:
    """Best-effort short, human-readable title for a table (heading or first cells)."""
    heading = " ".join((t.get("heading") or "").split())
    if not heading:
        return f"Table {t.get('index', '?')}"
    h = heading.lower()
    if "konzernbilanz" in h: return "Konzernbilanz"
    if "jahresbilanz"  in h: return "Jahresbilanz"
    if re.search(r"\bbilanz\b", h): return "Bilanz"
    if "gesamtergebnisrechnung" in h: return "Gesamtergebnisrechnung"
    if "ergebnisrechnung"       in h: return "Ergebnisrechnung"
    if "gewinn" in h and "verlust" in h: return "Gewinn- u. Verlustrechnung"
    if "kapitalflussrechnung"   in h: return "Kapitalflussrechnung"
    if "kapitalfluss"           in h: return "Kapitalflussrechnung"
    if "cashflow"               in h: return "Cashflow"
    short = re.sub(r"\s+(vom|zum|per|bis|für\s+das|für\s+den)\b.*$", "",
                   heading, flags=re.IGNORECASE)
    return short[:46].strip() or heading[:46]


def _overview_stmt_type(t: dict) -> int:
    """Determine statement type for a multi-year OVERVIEW table from its heading."""
    h = (t.get("heading") or "").lower()
    if "bilanz" in h: return 0
    if "guv" in h or "ergebnis" in h or "gewinn" in h: return 1
    if "kapitalfluss" in h or "cashflow" in h: return 2
    return _classify_table(t)


def _in_overview_status(t: dict) -> str:
    """Return 'included', 'excluded', or 'overridden' for a table."""
    if t.get("_include_in_overview") is False:
        return "excluded"
    if t.get("_override_applied") and t.get("_include_in_overview", True):
        return "overridden"
    if t.get("type", 99) in (0, 1, 2):
        return "included"
    return "excluded"


# ── Worker ─────────────────────────────────────────────────────────────────────

class ExtractorWorker:
    """Runs the Playwright + PDF extraction pipeline in a dedicated asyncio thread."""

    def __init__(self, to_gui: queue.Queue):
        """Set up the worker's queues and thread; the browser/loop are created lazily."""
        self._cmd_q: queue.Queue = queue.Queue()
        self._to_gui             = to_gui
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._confirm_event: Optional[asyncio.Event]    = None
        self._pw                                        = None
        self._done = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def send(self, cmd: str, payload=None):
        """Queue a (command, payload) for the worker thread to process."""
        self._cmd_q.put((cmd, payload))

    def confirm(self):
        """Signal a pending confirmation (e.g. CAPTCHA solved) to the worker."""
        if self._loop and self._confirm_event:
            self._loop.call_soon_threadsafe(self._confirm_event.set)

    def wait_done(self, timeout: float = 4.0):
        """Block until the worker thread has fully stopped, up to *timeout* seconds."""
        self._done.wait(timeout=timeout)

    def _run(self):
        """Thread entry point: create the asyncio loop and run the main coroutine."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        finally:
            self._done.set()

    async def _main(self):
        """Worker main loop: drain the command queue and dispatch until 'quit'."""
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            self._pw      = pw
            self._browser = None
            self._page    = None
            self._emit("ready", None)
            while True:
                try:
                    cmd, payload = self._cmd_q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.05)
                    continue
                if cmd == "quit":
                    if self._browser:
                        try:
                            await self._browser.close()
                        except Exception:
                            pass
                    return
                await self._dispatch(cmd, payload)

    async def _ensure_browser(self) -> bool:
        """Lazily launch the Playwright browser on first use."""
        if self._browser and self._browser.is_connected():
            return True
        self._emit("status", "Starting browser…")
        try:
            _before = _get_browser_hwnds()
            self._browser, _, self._page = await launch_browser(
                self._pw, interactive=False)
            await self._wait_and_minimize(exclude_hwnds=_before)
            return True
        except (SystemExit, Exception) as exc:
            self._emit("error", f"Could not launch browser: {exc}")
            return False

    async def _dispatch(self, cmd: str, payload):
        """Execute one GUI command and emit its results.

        Handles search, process_batch, recompute_overview (+ optional feedback
        bundle), export_v2 and navigate_home; errors surface as an 'error' event.
        """
        try:
            if cmd == "search":
                if not await self._ensure_browser():
                    self._emit("search_results", None)
                    return
                self._emit("status", f"Searching for '{payload}'…")
                if not await self._go_home(self._page):
                    self._emit("search_results", None)
                    return
                results = await run_search(self._page, payload, interactive=False)
                self._emit("search_results", results)

            elif cmd == "process_batch":
                doc_list, pdf_root = payload
                await self._process_batch_parallel(doc_list, pdf_root)

            elif cmd == "recompute_overview":
                company_id, all_tables, bundle_info, row_merges = payload
                loop = asyncio.get_event_loop()
                def _sync_recompute():
                    """Run the (blocking) consolidation off the event loop."""
                    return build_multi_year_tables(all_tables, row_merges=row_merges)
                overview = await loop.run_in_executor(None, _sync_recompute)
                self._emit("overview_ready", (company_id, overview))
                if bundle_info:
                    table, src_pdf, override_info = bundle_info
                    def _sync_bundle():
                        """Write a feedback bundle off the event loop."""
                        return write_feedback_bundle(table, src_pdf, override_info)
                    ok, path = await loop.run_in_executor(None, _sync_bundle)
                    self._emit("bundle_written", (ok, str(path) if path else ""))

            elif cmd == "export_v2":
                ov_tables, all_tables, result, out_path, dec, tho, pdf_dir, review_meta = payload
                self._emit("status", "Writing Excel…")
                loop = asyncio.get_event_loop()
                count, saved = await loop.run_in_executor(
                    None, export_to_excel_v2,
                    ov_tables, result, out_path, dec, tho, pdf_dir,
                    all_tables, review_meta)
                self._emit("exported", (count, saved))

            elif cmd == "navigate_home":
                if self._page and self._browser and self._browser.is_connected():
                    await self._go_home(self._page)
                self._emit("ready", None)

        except Exception as exc:
            self._emit("error", str(exc))

    async def _wait_and_minimize(self, timeout: float = 5.0,
                                  exclude_hwnds: set = None) -> set:
        """Wait briefly, then minimise the automation browser windows."""
        before   = exclude_hwnds or set()
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            after    = _get_browser_hwnds()
            new_wins = after - before
            if new_wins:
                _minimize_hwnds(new_wins)
                await asyncio.sleep(0.2)
                _hide_hwnds(new_wins)
                return new_wins
            await asyncio.sleep(0.15)
        after    = _get_browser_hwnds()
        new_wins = after - before
        if new_wins:
            _minimize_hwnds(new_wins)
            _hide_hwnds(new_wins)
        return new_wins

    async def _go_home(self, page, retries: int = 4) -> bool:
        """Navigate the browser back to the register home page."""
        for attempt in range(1, retries + 1):
            try:
                await page.goto(BASE_URL, timeout=PAGE_LOAD_TIMEOUT)
                await page.wait_for_load_state("domcontentloaded",
                                               timeout=PAGE_LOAD_TIMEOUT)
                return True
            except Exception:
                if attempt < retries:
                    wait = 2 ** attempt
                    self._emit("status", f"Retrying in {wait} s ({attempt}/{retries-1})…")
                    await asyncio.sleep(wait)
        self._emit("error", "Could not reach unternehmensregister.de.")
        return False

    async def _process_batch_parallel(self, doc_list: list,
                                       pdf_root: "Path | None" = None):
        """Download and extract every selected filing in sequence.

        Emits per-step batch_progress and a batch_doc_done (or batch_error) per
        filing, then batch_complete.
        """
        n            = len(doc_list)
        captcha_lock = asyncio.Lock()

        async def process_one(i: int, doc: dict):
            """Download and extract a single filing; emit its tables or an error."""
            label = f"{doc['company']} — {doc['fy']}"
            _fy   = doc.get("fy", "")
            def p(s, _i=i, _n=n):
                """Map a within-filing fraction *s* to overall batch progress (0..1)."""
                return min(1.0, (_i + s) / _n)
            self._emit("batch_progress", (p(0.0), f"({i+1}/{n}) Starting {_fy}…"))
            try:
                _before_p = _get_browser_hwnds()
                browser, _, page = await launch_browser(self._pw, interactive=False)
            except SystemExit:
                self._emit("batch_error", (i + 1, label, "Browser launch failed"))
                return
            await asyncio.sleep(0.5 + i * 0.3)
            _new_p = _get_browser_hwnds() - _before_p
            _minimize_hwnds(_new_p)
            _hide_hwnds(_new_p)
            try:
                await self._go_home(page)
                search_term = doc["company"].split(",")[0].strip()
                fresh = await run_search(page, search_term, interactive=False)
                if fresh:
                    match = next(
                        (r for r in fresh if r["fy"] == doc["fy"]
                         and r["doc_type"] == doc["doc_type"]), None)
                    if match:
                        doc = match

                async def locked_confirm():
                    """Serialise CAPTCHA confirmation so only one download prompts at a time."""
                    async with captcha_lock:
                        await self._wait_confirm()

                self._emit("batch_progress",
                           (p(0.25), f"({i+1}/{n}) Opening document {_fy}…"))
                ok = await open_document(page, doc,
                                         confirm_func=locked_confirm,
                                         interactive=False)
                if not ok:
                    self._emit("batch_error", (i+1, label, "Could not open document"))
                    return

                company_folder = None
                if pdf_root:
                    company_folder = pdf_root / sanitize_filename(
                        doc["company"].split(",")[0].strip())

                self._emit("batch_progress",
                           (p(0.55), f"({i+1}/{n}) Downloading {_fy}…"))
                path = await download_pdf(page, doc,
                                          captcha_cb=locked_confirm,
                                          interactive=False,
                                          pdf_dir=company_folder)
                if not path:
                    self._emit("batch_error", (i+1, label, "Download failed"))
                    return

                # Attach PDF path to doc for audit drill-down
                doc["pdf_path"] = str(path)

                self._emit("batch_progress",
                           (p(0.75), f"({i+1}/{n}) Extracting tables {_fy}…"))
                loop = asyncio.get_event_loop()
                tables = await loop.run_in_executor(
                    None, extract_tables_from_pdf, path)
                if tables:
                    for t in tables:
                        t["doc_label"] = doc["fy"]
                        t["_company"]  = doc.get("company", "")
                    self._emit("batch_progress",
                               (p(0.95), f"({i+1}/{n}) Done {_fy}"))
                    self._emit("batch_doc_done", (doc, tables))
                else:
                    self._emit("batch_error", (i+1, label, "No tables found"))

            except Exception as exc:
                self._emit("batch_error", (i+1, label, str(exc)))
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
                _minimize_all_browsers()

        await asyncio.gather(*[process_one(i, d) for i, d in enumerate(doc_list)])
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._page    = None
        self._emit("batch_complete", None)
        self._emit("status", f"All {n} document(s) processed.")

    async def _wait_confirm(self):
        """Await the GUI's confirmation signal (e.g. CAPTCHA solved)."""
        self._confirm_event = asyncio.Event()
        self._emit("need_confirm", None)
        await self._confirm_event.wait()

    def _emit(self, event: str, data):
        """Put a (event, data) message on the worker→GUI queue."""
        self._to_gui.put((event, data))


# ── Application ────────────────────────────────────────────────────────────────

class URExtractorApp(ctk.CTk):

    # ── Init ─────────────────────────────────────────────────────────────────

    """The application window and controller (CustomTkinter CTk).

    Owns the multi-company session, renders every screen, and brokers all slow
    work to a background ExtractorWorker over two queues: commands go out via
    self._worker.send; results arrive as events drained by _poll() every 100 ms
    and routed by _handle(). The GUI thread never blocks on browser, PDF,
    consolidation, or export work.
    """
    def __init__(self):
        """Build the window, load preferences, start the worker, and render the shell."""
        self._theme_name = _USER_PREFS.get("theme", DEFAULT_THEME)
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        super().__init__()

        self.title("UR Financial Extractor")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(WINDOW_MIN_W, WINDOW_MIN_H)
        self.configure(fg_color=T["BG"])

        # ── User preferences ─────────────────────────────────────────────
        _default_pdf = str(Path.home() / "Downloads" / "UR_Extracts")
        _default_log = str(Path.home() / "Downloads" / "UR_Extracts" / "logs")
        self._decimal_sep  = _USER_PREFS.get("decimal_sep",  ",")
        self._thousand_sep = "." if self._decimal_sep == "," else ","
        self._pdf_dir      = Path(_USER_PREFS.get("pdf_dir", _default_pdf)).expanduser()
        self._log_dir      = Path(_USER_PREFS.get("log_dir", _default_log)).expanduser()
        self._log_together = _USER_PREFS.get("log_together", True)
        self._log_delete   = _USER_PREFS.get("log_delete_on_close", False)
        self._currency_unit = _USER_PREFS.get("currency_unit", DEFAULT_CURRENCY)
        self._show_std_id   = _USER_PREFS.get("show_std_id", False)

        # ── Multi-company session model ───────────────────────────────────
        self._session: dict = {"companies": [], "active_company_id": None}

        # ── Other app state ───────────────────────────────────────────────
        self._results:         list  = []
        self._result_vars:     list  = []
        self._co_expanded:     dict  = {}
        self._active_inner_tab: int  = 0    # 0=Bilanz, 1=GuV, 2=CF
        self._active_outer_tab: str  = "OVERVIEW"
        self._canvas_state:    str   = "search"
        self._rail_mode:       Optional[str] = None   # "audit" | "review"
        self._captcha_pending:  bool  = False
        self._log_visible:      bool  = False
        self._bundle_history:   list  = []   # list of (ok: bool, path_str: str), max 3
        self._grid_row_descs:   dict  = {}   # iid -> raw desc; populated by _draw_financial_grid
        self._at_collapsed:     dict  = {}   # All-Tables section key -> collapsed bool
        self._at_selected:      set   = set()  # id(table) of bulk-selected rows
        self._at_id_map:        dict  = {}   # id(table) -> table (current All-Tables view)
        self._lib_save_after:   object = None  # pending debounced library-save timer
        self._lib_pending_co:   dict  = None  # company queued for the next library save
        self._bundle_tip:       object = None  # active tooltip Toplevel or None

        # ── Queue + worker ───────────────────────────────────────────────
        self._gui_q  = queue.Queue()
        self._worker = ExtractorWorker(self._gui_q)

        # ── Build UI ─────────────────────────────────────────────────────
        self._build_ui()
        self.after(100, self._poll)

    # ── Session helpers ───────────────────────────────────────────────────────

    @property
    def _active_company(self):
        """The currently selected company-session dict, or None."""
        cid = self._session["active_company_id"]
        if cid is None:
            return None
        return next((c for c in self._session["companies"] if c["id"] == cid), None)

    def _make_company(self, name="") -> dict:
        """Create an empty company-session record with a fresh id."""
        return {
            "id": str(uuid.uuid4()),
            "name": name,
            "all_tables": [],
            "overview_tables": [],
            "doc_sections": [],
            "review_line_items": [],
            "review_tables": [],
        }

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Row 0: status track (fixed height)
        # Row 1: progress bar (fixed 4px)
        # Row 2: content area (expands)
        """Lay out the fixed 3-column shell (status track, rails, center canvas)."""
        self.grid_rowconfigure(0, minsize=LAYOUT["status_bar_h"])
        self.grid_rowconfigure(1, minsize=4)
        self.grid_rowconfigure(2, weight=1)
        # Col 0: left rail (240px), Col 1: center (expands), Col 2: right rail
        self.grid_columnconfigure(0, minsize=LAYOUT["left_rail_w"], weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, minsize=0, weight=0)

        self._build_status_track()
        self._build_progress_bar()
        self._build_left_rail()
        self._build_center_canvas()
        self._build_right_rail()
        self._build_settings_panel()

        self._switch_canvas("search")

    def _build_status_track(self):
        """Build the top bar: breadcrumb, Export/Log/Settings, review chips, bundle dot."""
        sf = tk.Frame(self, bg=T["STATUSBAR"], height=LAYOUT["status_bar_h"])
        sf.grid(row=0, column=0, columnspan=3, sticky="ew")
        sf.grid_columnconfigure(1, weight=1)
        sf.grid_propagate(False)
        # Bottom border
        tk.Frame(sf, bg=T["BORDER"], height=1).place(relx=0, rely=1.0, relwidth=1.0, anchor="sw")

        left = tk.Frame(sf, bg=T["STATUSBAR"])
        left.grid(row=0, column=0, sticky="w", padx=(12, 0))
        self._status_dot = tk.Label(left, text="●", bg=T["STATUSBAR"], fg=T["N400"],
                                    font=(_SANS, 9))
        self._status_dot.pack(side="left", padx=(0, 6))
        self._breadcrumb_lbl = tk.Label(left, text="Starting…", bg=T["STATUSBAR"],
                                        fg=T["N600"], font=(_SANS, 11))
        self._breadcrumb_lbl.pack(side="left")

        # CAPTCHA banner (center, hidden)
        self._captcha_lbl = tk.Label(sf,
            text="⚠  CAPTCHA needed — solve in browser, then click  →",
            bg=T["warning"], fg=T["BG"], font=(_SANS, 10, "bold"),
            cursor="hand2", padx=10)
        self._captcha_lbl.grid(row=0, column=1, sticky="ew", padx=4, pady=6)
        self._captcha_lbl.grid_remove()
        self._captcha_lbl.bind("<Button-1>", lambda _: self._inline_captcha_confirm())

        right = tk.Frame(sf, bg=T["STATUSBAR"])
        right.grid(row=0, column=2, sticky="e", padx=(0, 8))

        # Line-items review chip
        self._li_review_chip = tk.Label(right, text="⚠ 0 items", bg=T["warning50"],
            fg=T["warning700"], font=(_SANS, 9, "bold"), cursor="hand2", padx=6, pady=2,
            relief="flat")
        self._li_review_chip.pack(side="left", padx=(0, 4))
        self._li_review_chip.pack_forget()
        self._li_review_chip.bind("<Button-1>", lambda _: self._toggle_review_rail())

        # Tables review chip
        self._tbl_review_chip = tk.Label(right, text="▸ 0 tables", bg=T["warning50"],
            fg=T["warning700"], font=(_SANS, 9, "bold"), cursor="hand2", padx=6, pady=2)
        self._tbl_review_chip.pack(side="left", padx=(0, 4))
        self._tbl_review_chip.pack_forget()
        self._tbl_review_chip.bind("<Button-1>", lambda _: self._switch_canvas("all_tables"))

        # Bundle status dot
        self._bundle_dot = tk.Label(right, text="●", bg=T["STATUSBAR"], fg=T["N400"],
                                    font=(_SANS, 9))
        self._bundle_dot.pack(side="left", padx=(0, 6))
        self._bundle_dot.bind("<Enter>", self._show_bundle_tip)
        self._bundle_dot.bind("<Leave>", self._hide_bundle_tip)

        # Export button
        self._export_btn = ctk.CTkButton(right, text="Export", width=72, height=28,
            font=F_SM, corner_radius=RADIUS["sm"],
            fg_color=T["P600"], hover_color=T["P700"],
            state="disabled", command=self._on_export_excel)
        self._export_btn.pack(side="left", padx=(0, 6))

        # Log + settings
        tk.Button(right, text="Log", bg=T["STATUSBAR"], fg=T["N400"], relief="flat",
            font=(_SANS, 9), activebackground=T["N100"],
            command=self._toggle_log_panel).pack(side="left", padx=2)
        tk.Button(right, text="⚙", bg=T["STATUSBAR"], fg=T["N400"], relief="flat",
            font=(_SANS, 11), activebackground=T["N100"],
            command=self._open_settings).pack(side="left", padx=2)
        self._status_frame = sf

    def _build_progress_bar(self):
        """Build the thin batch-progress bar under the status track."""
        self._progress = ctk.CTkProgressBar(self, height=4, corner_radius=0,
                                             fg_color=T["STATUSBAR"],
                                             progress_color=T["P600"])
        self._progress.set(0)
        self._progress.grid(row=1, column=0, columnspan=3, sticky="ew")

    def _build_left_rail(self):
        """Build the left company rail (New Searches + Library sections)."""
        rail = ctk.CTkFrame(self, fg_color=T["RAIL"], corner_radius=0, border_width=0)
        rail.grid(row=2, column=0, sticky="nsew")
        rail.grid_rowconfigure(1, weight=1)
        rail.grid_columnconfigure(0, weight=1)
        self._left_rail = rail
        # Right separator
        tk.Frame(rail, bg=T["N200"], width=1).place(relx=1.0, rely=0,
                                                     relheight=1.0, anchor="ne")

        # Header row
        hdr = tk.Frame(rail, bg=T["RAIL"])
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
        hdr.grid_columnconfigure(0, weight=1)
        tk.Label(hdr, text="Companies", bg=T["RAIL"], fg=T["N500"],
                 font=(_SANS, 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Button(hdr, text="+", bg=T["RAIL"], fg=T["P600"], relief="flat",
                  font=(_SANS, 13, "bold"), cursor="hand2",
                  activebackground=T["P100"],
                  command=self._on_add_company).grid(row=0, column=1)

        # Company list (scrollable)
        co_list = ctk.CTkScrollableFrame(rail, fg_color="transparent",
            scrollbar_button_color=T["N300"], corner_radius=0)
        co_list.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        co_list.grid_columnconfigure(0, weight=1)
        self._company_list_frame = co_list

        self._refresh_company_rail()

    def _build_center_canvas(self):
        """Build the center canvas shell with outer/inner tabs and swappable content."""
        canvas = ctk.CTkFrame(self, fg_color=T["BG"], corner_radius=0)
        canvas.grid(row=2, column=1, sticky="nsew")
        canvas.grid_rowconfigure(2, weight=1)
        canvas.grid_columnconfigure(0, weight=1)
        self._center_canvas = canvas

        # Outer tab strip (40px) — row 0
        self._outer_tab_strip = tk.Frame(canvas, bg=T["RAIL"],
                                          height=LAYOUT["outer_tab_h"])
        self._outer_tab_strip.grid(row=0, column=0, sticky="ew")
        self._outer_tab_strip.grid_propagate(False)
        # bottom border of outer strip
        tk.Frame(canvas, bg=T["N200"], height=1).grid(row=0, column=0, sticky="sew")

        self._outer_tab_widgets: dict = {}
        for name in ["OVERVIEW", "All Tables"]:
            cell = tk.Frame(self._outer_tab_strip, bg=T["RAIL"], cursor="hand2")
            cell.pack(side="left", fill="y", padx=0)
            lbl = tk.Label(cell, text=name, bg=T["RAIL"], fg=T["N500"],
                           font=(_SANS, 11), cursor="hand2", padx=16)
            lbl.pack(side="top", expand=True, fill="both")
            ind = tk.Frame(cell, bg=T["RAIL"], height=LAYOUT["outer_tab_active_w"])
            ind.pack(side="bottom", fill="x")
            lbl.bind("<Button-1>", lambda e, n=name: self._on_outer_tab(n))
            cell.bind("<Button-1>", lambda e, n=name: self._on_outer_tab(n))
            self._outer_tab_widgets[name] = {"cell": cell, "lbl": lbl, "ind": ind}

        # Inner tab strip (32px) — row 1 (only under OVERVIEW)
        self._inner_tab_strip = tk.Frame(canvas, bg=T["BG"],
                                          height=LAYOUT["inner_tab_h"])
        self._inner_tab_strip.grid(row=1, column=0, sticky="ew")
        self._inner_tab_strip.grid_propagate(False)
        tk.Frame(canvas, bg=T["N200"], height=1).grid(row=1, column=0, sticky="sew")

        self._inner_tab_widgets: dict = {}
        for stype, sname in {0: "Bilanz", 1: "GuV", 2: "Cashflow"}.items():
            cell = tk.Frame(self._inner_tab_strip, bg=T["BG"], cursor="hand2")
            cell.pack(side="left", fill="y")
            lbl = tk.Label(cell, text=sname, bg=T["BG"], fg=T["N500"],
                           font=(_SANS, 10), cursor="hand2", padx=12)
            lbl.pack(side="top", expand=True, fill="both")
            ind = tk.Frame(cell, bg=T["BG"], height=2)
            ind.pack(side="bottom", fill="x")
            lbl.bind("<Button-1>", lambda e, s=stype: self._on_inner_tab(s))
            cell.bind("<Button-1>", lambda e, s=stype: self._on_inner_tab(s))
            self._inner_tab_widgets[stype] = {"cell": cell, "lbl": lbl, "ind": ind}

        # Content area — row 2
        content = tk.Frame(canvas, bg=T["BG"])
        content.grid(row=2, column=0, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        self._content_area = content

        # Build the three content frames
        self._build_search_content(content)
        self._build_overview_content(content)
        self._build_all_tables_content(content)

        self._active_outer_tab = "OVERVIEW"
        self._active_inner_tab = 0
        self._update_outer_tab_style()
        self._update_inner_tab_style()

    def _build_search_content(self, parent):
        """Build the search screen (name field, results list, process button)."""
        sf = ctk.CTkFrame(parent, fg_color=T["BG"], corner_radius=0)
        sf.grid(row=0, column=0, sticky="nsew")
        sf.grid_rowconfigure(2, weight=1)
        sf.grid_columnconfigure(0, weight=1)
        self._search_frame = sf

        # Search input area
        search_area = ctk.CTkFrame(sf, fg_color="transparent")
        search_area.grid(row=0, column=0, sticky="ew", padx=32, pady=(40, 8))
        search_area.grid_columnconfigure(0, weight=1)

        self._entry = ctk.CTkEntry(
            search_area, placeholder_text="Search for a German company…",
            font=F_BODY, height=48, corner_radius=R_PILL,
            fg_color=T["N0"], border_color=T["N200"],
            text_color=T["N900"], placeholder_text_color=T["N400"])
        self._entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._entry.bind("<Return>", lambda _: self._on_search())

        self._search_btn = ctk.CTkButton(
            search_area, text="Search", width=100, height=48,
            font=F_H2, corner_radius=R_PILL, state="disabled",
            fg_color=T["P600"], hover_color=T["P700"],
            command=self._on_search)
        self._search_btn.grid(row=0, column=1)

        # Select-all + count row
        sa_row = ctk.CTkFrame(sf, fg_color="transparent")
        sa_row.grid(row=1, column=0, sticky="ew", padx=32, pady=(0, 4))
        self._sel_all_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(sa_row, text="Select all", variable=self._sel_all_var,
                        font=F_XS, text_color=T["N600"],
                        fg_color=T["P600"], hover_color=T["P700"],
                        command=self._toggle_select_all).pack(side="left")
        self._sel_count_lbl = ctk.CTkLabel(sa_row, text="0 selected",
                                            font=F_XS, text_color=T["N400"])
        self._sel_count_lbl.pack(side="right")

        # Results scrollable area
        self._results_scroll = ctk.CTkScrollableFrame(
            sf, fg_color="transparent",
            scrollbar_button_color=T["N200"], corner_radius=0)
        self._results_scroll.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 8))
        self._results_scroll.grid_columnconfigure(0, weight=1)
        self._results_frame = self._results_scroll

        # Process button
        self._process_btn = ctk.CTkButton(
            sf, text="Process Selected  (0)", height=46,
            font=F_H1, corner_radius=R_PILL, state="disabled",
            fg_color=T["P600"], hover_color=T["P700"],
            command=self._on_process_selected)
        self._process_btn.grid(row=3, column=0, sticky="ew", padx=32, pady=(0, 20))

        # Progress cards area
        self._progress_cards_frame = ctk.CTkFrame(sf, fg_color="transparent")
        self._progress_cards_frame.grid(row=4, column=0, sticky="ew", padx=24)
        self._progress_cards: dict = {}

        sf.grid_remove()

    def _build_overview_content(self, parent):
        """Build the OVERVIEW screen (financial-grid Treeview + debug log drawer)."""
        gf = ctk.CTkFrame(parent, fg_color=T["BG"], corner_radius=0)
        gf.grid(row=0, column=0, sticky="nsew")
        gf.grid_rowconfigure(0, weight=1)
        gf.grid_columnconfigure(0, weight=1)
        self._overview_frame = gf

        # Financial grid (ttk Treeview)
        tree_frame = tk.Frame(gf, bg=T["N200"], bd=0)
        tree_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(tree_frame, show="headings", selectmode="extended")
        self._tree.grid(row=0, column=0, sticky="nsew")
        vs = ttk.Scrollbar(tree_frame, orient="vertical",   command=self._tree.yview)
        hs = ttk.Scrollbar(tree_frame, orient="horizontal", command=self._tree.xview)
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        self._tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self._tree.bind("<ButtonRelease-1>", self._on_tree_click)
        self._tree.bind("<Button-3>", self._show_overview_ctx)

        # Debug log drawer
        self._log_hdr   = None
        self._log_frame = None
        self._log_text  = None
        self._build_log_drawer(gf, row=1)

        self._style_treeview()
        gf.grid_remove()

    def _build_all_tables_content(self, parent):
        """Build the All Tables screen (bulk action bar + scrollable segmented list)."""
        f = ctk.CTkFrame(parent, fg_color=T["BG"], corner_radius=0)
        f.grid(row=0, column=0, sticky="nsew")
        f.grid_rowconfigure(1, weight=1)
        f.grid_columnconfigure(0, weight=1)
        self._all_tables_frame = f

        # Bulk-selection action bar (row 0) — shown only when ≥1 row is ticked.
        bar = ctk.CTkFrame(f, fg_color=T["P50"], corner_radius=0, height=40)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        self._at_bulk_bar = bar
        self._at_bulk_lbl = ctk.CTkLabel(bar, text="0 selected", font=F_SM,
                                         text_color=T["N900"], anchor="w")
        self._at_bulk_lbl.pack(side="left", padx=14)
        ctk.CTkButton(bar, text="Clear", width=64, height=26, font=F_XS,
                      corner_radius=R_SM, fg_color=T["N100"], text_color=T["N700"],
                      hover_color=T["N200"],
                      command=self._at_clear_selection).pack(side="right", padx=10)
        ctk.CTkButton(bar, text="Set type ▾", width=110, height=26, font=F_XS,
                      corner_radius=R_SM, fg_color=T["P600"], text_color=T["N0"],
                      hover_color=T["P700"],
                      command=self._at_bulk_type_menu).pack(side="right", padx=(0, 6))
        bar.grid_remove()

        scroll = ctk.CTkScrollableFrame(f, fg_color=T["BG"],
            scrollbar_button_color=T["N300"], corner_radius=0)
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        self._all_tables_scroll = scroll
        f.grid_remove()

    def _build_log_drawer(self, parent, row: int):
        """Build the collapsible dark debug-log console."""
        log_hdr = tk.Frame(parent, bg="#0d1117", height=26)
        log_hdr.grid(row=row, column=0, sticky="ew")
        log_hdr.grid_remove()
        self._log_hdr = log_hdr

        tk.Label(log_hdr, text=" ⬛  Debug Log", bg="#0d1117", fg="#6b7280",
                 font=("Consolas", 9)).pack(side="left")
        tk.Button(log_hdr, text="Clear", bg="#0d1117", fg="#6b7280",
                  relief="flat", font=("Consolas", 9),
                  command=self._clear_log).pack(side="right", padx=4)

        log_frame = tk.Frame(parent, bg="#0d1117")
        log_frame.grid(row=row+1, column=0, sticky="ew")
        log_frame.grid_remove()
        log_frame.grid_columnconfigure(0, weight=1)
        self._log_frame = log_frame

        self._log_text = tk.Text(log_frame, bg="#0d1117", fg="#9ca3af",
                                  font=("Consolas", 10), state="disabled",
                                  wrap="word", height=8, relief="flat",
                                  selectbackground="#1f538d")
        self._log_text.grid(row=0, column=0, sticky="ew")
        log_sb = ttk.Scrollbar(log_frame, orient="vertical",
                                command=self._log_text.yview)
        log_sb.grid(row=0, column=1, sticky="ns")
        self._log_text.configure(yscrollcommand=log_sb.set)
        self._log_text.tag_config("err",  foreground="#ef4444")
        self._log_text.tag_config("ok",   foreground="#22c55e")
        self._log_text.tag_config("info", foreground="#9ca3af")

    def _build_right_rail(self):
        """Build the right-rail container; its content is rebuilt per mode."""
        rail = ctk.CTkFrame(self, fg_color=T["RAIL"], corner_radius=0, width=LAYOUT["right_rail_w"])
        self._right_rail = rail
        # Persistent left border line — kept across panel rebuilds.
        self._right_rail_border = tk.Frame(rail, bg=T["N200"], width=1)
        self._right_rail_border.place(x=0, y=0, relheight=1.0)

    # ── Company rail ──────────────────────────────────────────────────────────

    def _refresh_company_rail(self):
        """Re-render the left rail: New Searches (recent first) + Library (alphabetical)."""
        for w in self._company_list_frame.winfo_children():
            w.destroy()
        row = 0

        # ── Section 1: New Searches (this session, most-recent first) ──────
        companies = list(self._session["companies"])
        self._build_rail_section_header("NEW SEARCHES", row); row += 1
        if companies:
            for co in reversed(companies):
                self._build_company_row(co, row); row += 1
        else:
            self._build_rail_empty("No searches yet", row); row += 1

        # ── Section 2: Library (saved on disk, alphabetical) ──────────────
        try:
            entries = list_library_entries()
        except Exception:
            entries = []
        self._build_rail_section_header("LIBRARY", row); row += 1
        if entries:
            session_norms = {_normalize_for_override_key(c.get("name", ""))
                             for c in companies}
            for e in entries:
                in_session = _normalize_for_override_key(e["name"]) in session_norms
                self._build_library_row(e, row, in_session); row += 1
        else:
            self._build_rail_empty("Empty — finish a search to save it here", row); row += 1

    def _build_rail_section_header(self, text: str, row_idx: int):
        """Render a left-rail section header label."""
        hdr = tk.Frame(self._company_list_frame, bg=T["RAIL"])
        hdr.grid(row=row_idx, column=0, sticky="ew", padx=12, pady=(12, 2))
        tk.Label(hdr, text=text, bg=T["RAIL"], fg=T["N400"],
                 font=(_SANS, 8, "bold")).pack(side="left")

    def _build_rail_empty(self, text: str, row_idx: int):
        """Render a muted 'empty' placeholder row in the left rail."""
        tk.Label(self._company_list_frame, text=text, bg=T["RAIL"], fg=T["N400"],
                 font=(_SANS, 9), anchor="w", justify="left", wraplength=210
                 ).grid(row=row_idx, column=0, sticky="ew", padx=14, pady=(2, 6))

    def _build_library_row(self, entry: dict, row_idx: int, in_session: bool):
        """Render one saved-library entry row (name, date, counts; click to open)."""
        outer = tk.Frame(self._company_list_frame, bg=T["RAIL"], cursor="hand2")
        outer.grid(row=row_idx, column=0, sticky="ew")
        outer.grid_columnconfigure(1, weight=1)
        tk.Frame(outer, bg=T["RAIL"], width=2).grid(row=0, column=0, rowspan=2, sticky="ns")
        name = (entry.get("name") or "(Unnamed)")[:30]
        tk.Label(outer, text=name, bg=T["RAIL"],
                 fg=T["N500"] if in_session else T["N700"],
                 font=(_SANS, 11), anchor="w").grid(
            row=0, column=1, sticky="ew", padx=(8, 4), pady=(6, 1))
        saved = (entry.get("saved_at", "") or "")[:10]
        n_t = entry.get("n_tables", 0)
        sub = f"{saved} · {n_t} tables" + ("  · open" if in_session else "")
        tk.Label(outer, text=sub, bg=T["RAIL"], fg=T["N400"],
                 font=(_SANS, 9), anchor="w").grid(
            row=1, column=1, sticky="ew", padx=(8, 4), pady=(0, 6))
        for w in (outer, *outer.winfo_children()):
            w.bind("<Button-1>", lambda e, en=entry: self._open_library_entry(en))
            w.bind("<Button-3>", lambda e, en=entry: self._library_row_ctx(e, en))

    def _open_library_entry(self, entry: dict):
        """Load a library snapshot into the session (or just select it if already open)."""
        norm = _normalize_for_override_key(entry.get("name", ""))
        for c in self._session["companies"]:
            if _normalize_for_override_key(c.get("name", "")) == norm:
                self._select_company(c["id"])   # already loaded this session
                return
        co = load_library_company(entry["path"])
        if not co:
            messagebox.showerror("Library", "Could not load this library entry.")
            return
        existing_ids = {c["id"] for c in self._session["companies"]}
        if not co.get("id") or co["id"] in existing_ids:
            co["id"] = str(uuid.uuid4())
        self._session["companies"].append(co)
        self._session["active_company_id"] = co["id"]
        self._select_company(co["id"])

    def _library_row_ctx(self, event, entry: dict):
        """Right-click menu for a library entry (Open / Delete)."""
        menu = tk.Menu(self, tearoff=0, bg=T["N0"], fg=T["N900"],
                       activebackground=T["P100"], font=(_SANS, 10))
        menu.add_command(label="Open", command=lambda: self._open_library_entry(entry))
        menu.add_separator()
        menu.add_command(label="Delete from library…",
                         command=lambda: self._delete_library_entry(entry))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _delete_library_entry(self, entry: dict):
        """Confirm and delete a library snapshot (the in-session copy stays)."""
        if not messagebox.askyesno(
                "Delete from library",
                f"Remove '{entry.get('name','')}' from the library?\n"
                "This deletes the saved snapshot file (the current session stays)."):
            return
        try:
            delete_library_entry(entry["path"])
        except Exception:
            pass
        self._refresh_company_rail()

    def _build_company_row(self, co: dict, row_idx: int):
        """Render one in-session company row (active stripe, counts, review dot)."""
        active = co["id"] == self._session.get("active_company_id")
        row_bg = T["P100"] if active else T["RAIL"]
        outer = tk.Frame(self._company_list_frame, bg=row_bg, cursor="hand2")
        outer.grid(row=row_idx, column=0, sticky="ew")
        outer.grid_columnconfigure(1, weight=1)
        # Active stripe
        stripe_color = T["P600"] if active else row_bg
        tk.Frame(outer, bg=stripe_color, width=2).grid(row=0, column=0, rowspan=2, sticky="ns")
        # Name
        name = (co.get("name") or "(Unnamed)")[:30]
        tk.Label(outer, text=name, bg=row_bg,
                 fg=T["N900"] if active else T["N700"],
                 font=(_SANS, 11, "bold" if active else "normal"),
                 anchor="w").grid(row=0, column=1, sticky="ew", padx=(8, 4), pady=(6, 1))
        # Subtitle
        n_tbl = len(co.get("all_tables", []))
        n_sec = len(co.get("doc_sections", []))
        subtitle = f"{n_sec} filing{'s' if n_sec != 1 else ''} · {n_tbl} tables"
        tk.Label(outer, text=subtitle, bg=row_bg,
                 fg=T["N400"], font=(_SANS, 9), anchor="w"
                 ).grid(row=1, column=1, sticky="ew", padx=(8, 4), pady=(0, 6))
        # Review dot
        n_rev = len(co.get("review_line_items", []))
        if n_rev:
            tk.Label(outer, text="●", bg=row_bg,
                     fg=T["warning"], font=(_SANS, 8)).grid(row=0, column=2, padx=(0, 8))
        for w in (outer, *outer.winfo_children()):
            w.bind("<Button-1>", lambda e, cid=co["id"]: self._select_company(cid))

    def _select_company(self, company_id: str):
        """Make a company active and show its OVERVIEW (or the search screen if empty)."""
        self._session["active_company_id"] = company_id
        self._at_selected.clear()   # bulk selection is per-company
        self._refresh_company_rail()
        co = self._active_company
        if co and co.get("all_tables"):
            self._switch_canvas("overview")
            self._rebuild_overview()
            self._draw_financial_grid(self._active_inner_tab)
            self._update_review_chips()
            self._update_breadcrumb()
        else:
            self._switch_canvas("search")
            self._entry.delete(0, "end")
            self._clear_results()

    def _on_add_company(self):
        """Add a fresh company slot and switch to the search screen."""
        co = self._make_company("(Searching…)")
        self._session["companies"].append(co)
        self._session["active_company_id"] = co["id"]
        self._refresh_company_rail()
        self._switch_canvas("search")
        self._entry.delete(0, "end")
        self._clear_results()
        self._search_btn.configure(state="normal")
        self._set_breadcrumb("Search for a company")

    # ── Outer / inner tabs ────────────────────────────────────────────────────

    def _on_outer_tab(self, name: str):
        """Handle OVERVIEW / All-Tables outer-tab selection."""
        self._active_outer_tab = name
        self._update_outer_tab_style()
        if name == "OVERVIEW":
            self._switch_canvas("overview")
        else:
            self._switch_canvas("all_tables")
        self._update_breadcrumb()

    def _on_inner_tab(self, stype: int):
        """Handle Bilanz / GuV / Cashflow inner-tab selection."""
        self._active_inner_tab = stype
        self._update_inner_tab_style()
        self._draw_financial_grid(stype)
        self._update_breadcrumb()

    def _update_outer_tab_style(self):
        """Restyle the outer tabs to reflect the active one (indigo bottom stripe)."""
        for name, w in self._outer_tab_widgets.items():
            active = (name == self._active_outer_tab)
            w["lbl"].configure(fg=T["N900"] if active else T["N500"],
                               font=(_SANS, 11, "bold") if active else (_SANS, 11))
            w["ind"].configure(bg=T["P600"] if active else T["RAIL"])

    def _update_inner_tab_style(self):
        """Restyle inner tabs (active = bold; the accent is carried by the outer stripe)."""
        for stype, w in self._inner_tab_widgets.items():
            active = (stype == self._active_inner_tab)
            w["lbl"].configure(fg=T["N900"] if active else T["N500"],
                               font=(_SANS, 10, "bold") if active else (_SANS, 10))
            # No underline on inner tabs — outer tab's P600 stripe carries the accent

    # ── Canvas state machine ──────────────────────────────────────────────────

    def _switch_canvas(self, state: str):
        """Swap the center canvas between 'search', 'overview' and 'all_tables'."""
        self._canvas_state = state
        if state == "search":
            self._outer_tab_strip.grid_remove()
            self._inner_tab_strip.grid_remove()
            self._search_frame.grid(row=0, column=0, sticky="nsew")
            self._overview_frame.grid_remove()
            self._all_tables_frame.grid_remove()
        elif state == "overview":
            self._outer_tab_strip.grid()
            self._inner_tab_strip.grid()
            self._search_frame.grid_remove()
            self._overview_frame.grid(row=0, column=0, sticky="nsew")
            self._all_tables_frame.grid_remove()
            self._active_outer_tab = "OVERVIEW"
            self._update_outer_tab_style()
        elif state == "all_tables":
            self._outer_tab_strip.grid()
            self._inner_tab_strip.grid_remove()
            self._search_frame.grid_remove()
            self._overview_frame.grid_remove()
            self._all_tables_frame.grid(row=0, column=0, sticky="nsew")
            self._active_outer_tab = "All Tables"
            self._update_outer_tab_style()
            self._refresh_all_tables()

    # ── All Tables view ───────────────────────────────────────────────────────

    def _refresh_all_tables(self):
        """Re-render All Tables: segment by effective type → year; prune stale selection."""
        for w in self._all_tables_scroll.winfo_children():
            w.destroy()
        all_tables = [t for t in (self._active_company or {}).get("all_tables", [])
                      if not t.get("multi_year")]
        # Fresh id-map each render; drop selections for tables no longer present.
        self._at_id_map = {id(t): t for t in all_tables}
        self._at_selected &= set(self._at_id_map.keys())
        if not all_tables:
            tk.Label(self._all_tables_scroll, text="No tables extracted yet.",
                     bg=T["BG"], fg=T["N400"], font=(_SANS, 11)).grid(padx=20, pady=40)
            self._update_bulk_bar()
            return

        # Segment by statement type (the SAME classification the consolidator uses),
        # then by year. Tables in the Bilanz/GuV/Cashflow segments feed that
        # consolidation; Other tables feed nothing.
        from collections import defaultdict
        seg: dict = defaultdict(lambda: defaultdict(list))
        for t in all_tables:
            seg[effective_table_type(t)][t.get("doc_label", "") or "Unknown filing"].append(t)

        grid_row = 0
        for tp in (0, 1, 2, 99):
            if tp not in seg:
                continue
            type_name = _TYPE_LABELS.get(tp, "Other")
            n_tables  = sum(len(v) for v in seg[tp].values())
            tkey      = f"type:{tp}"
            tcollapsed = self._at_collapsed.get(tkey, False)
            grid_row = self._build_at_type_header(type_name, n_tables, tkey,
                                                  tcollapsed, grid_row)
            if tcollapsed:
                continue
            for yr in sorted(seg[tp].keys(), reverse=True):
                ykey = f"{tkey}|{yr}"
                ycollapsed = self._at_collapsed.get(ykey, False)
                grid_row = self._build_at_year_header(yr, len(seg[tp][yr]), ykey,
                                                      ycollapsed, grid_row)
                if ycollapsed:
                    continue
                alt = False
                for t in seg[tp][yr]:
                    self._build_table_row(t, grid_row, alt=alt)
                    grid_row += 1
                    alt = not alt
        self._update_bulk_bar()

    def _toggle_at_section(self, key: str):
        """Collapse/expand an All-Tables type or year section."""
        self._at_collapsed[key] = not self._at_collapsed.get(key, False)
        self._refresh_all_tables()

    # ── All-Tables bulk selection ─────────────────────────────────────────────

    def _at_toggle_select(self, t: dict):
        """Toggle bulk selection of one table and refresh the view + bulk bar."""
        tid = id(t)
        if tid in self._at_selected:
            self._at_selected.discard(tid)
        else:
            self._at_selected.add(tid)
        self._refresh_all_tables()
        self._update_bulk_bar()

    def _at_clear_selection(self):
        """Clear the All-Tables bulk selection."""
        self._at_selected.clear()
        self._refresh_all_tables()
        self._update_bulk_bar()

    def _update_bulk_bar(self):
        """Show/hide the bulk action bar and update its 'N selected' label."""
        n = len(self._at_selected)
        if n:
            self._at_bulk_lbl.configure(text=f"{n} selected")
            self._at_bulk_bar.grid()
        else:
            self._at_bulk_bar.grid_remove()

    def _at_bulk_type_menu(self):
        """Pop the 'Set type' menu for the current bulk selection."""
        if not self._at_selected:
            return
        menu = tk.Menu(self, tearoff=0, bg=T["N0"], fg=T["N900"],
                       activebackground=T["P100"], font=(_SANS, 10))
        for tp, label in _TYPE_LABELS.items():
            menu.add_command(label=f"Set {len(self._at_selected)} → {label}",
                             command=lambda ti=tp, tl=label: self._bulk_reclassify(ti, tl))
        try:
            x = self._at_bulk_bar.winfo_rootx() + 120
            y = self._at_bulk_bar.winfo_rooty() + 36
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _bulk_reclassify(self, new_type_int: int, new_type_label: str):
        """Re-type every selected table at once, persist each override, then recompute once."""
        tables = [self._at_id_map.get(tid) for tid in self._at_selected]
        tables = [t for t in tables if t]
        if not tables:
            return
        co = self._active_company or {}
        co_norm = self._active_co_norm()
        for t in tables:
            old_type = t.get("type", 99)
            t["type"] = new_type_int
            t["_override_applied"] = True
            t["_override_old_type"] = old_type
            include = t.get("_include_in_overview", True) is not False
            save_table_override(make_override_record(
                t, co_norm, new_type_label, include,
                note=f"bulk reclassified from {old_type} via GUI"))
        self._at_selected.clear()
        self._update_bulk_bar()
        # One overview recompute for the whole batch.
        self._worker.send("recompute_overview",
                          (co.get("id", ""), co.get("all_tables", []), None,
                           self._active_row_merges()))
        self._refresh_all_tables()

    def _build_at_type_header(self, name: str, n: int, key: str,
                              collapsed: bool, grid_row: int) -> int:
        """Render a collapsible statement-type segment header."""
        chevron = "▶" if collapsed else "▼"
        hdr = tk.Frame(self._all_tables_scroll, bg=T["SECTION"],
                       height=ROW_H["default"], cursor="hand2")
        hdr.grid(row=grid_row, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(1, weight=1)
        tk.Label(hdr, text=chevron, bg=T["SECTION"], fg=T["N600"],
                 font=(_SANS, 9)).grid(row=0, column=0, padx=(10, 4))
        tk.Label(hdr, text=name, bg=T["SECTION"], fg=T["N900"],
                 font=(_SANS, 11, "bold"), anchor="w").grid(row=0, column=1, sticky="w")
        tk.Label(hdr, text=f"{n} table{'s' if n != 1 else ''}", bg=T["SECTION"],
                 fg=T["N500"], font=(_SANS, 9)).grid(row=0, column=2, padx=12)
        tk.Frame(self._all_tables_scroll, bg=T["BORDER"], height=1
                 ).grid(row=grid_row, column=0, sticky="sew")
        for w in (hdr, *hdr.winfo_children()):
            w.bind("<Button-1>", lambda _e, k=key: self._toggle_at_section(k))
        return grid_row + 1

    def _build_at_year_header(self, year: str, n: int, key: str,
                              collapsed: bool, grid_row: int) -> int:
        """Render a collapsible fiscal-year sub-header within a type."""
        chevron = "▸" if collapsed else "▾"
        hdr = tk.Frame(self._all_tables_scroll, bg=T["RAIL"],
                       height=ROW_H["dense"], cursor="hand2")
        hdr.grid(row=grid_row, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(1, weight=1)
        tk.Label(hdr, text=chevron, bg=T["RAIL"], fg=T["N500"],
                 font=(_SANS, 8)).grid(row=0, column=0, padx=(28, 4))
        tk.Label(hdr, text=year, bg=T["RAIL"], fg=T["N700"],
                 font=(_SANS, 10, "bold"), anchor="w").grid(row=0, column=1, sticky="w")
        tk.Label(hdr, text=f"{n}", bg=T["RAIL"], fg=T["N400"],
                 font=(_SANS, 9)).grid(row=0, column=2, padx=12)
        for w in (hdr, *hdr.winfo_children()):
            w.bind("<Button-1>", lambda _e, k=key: self._toggle_at_section(k))
        return grid_row + 1

    def _build_table_row(self, t: dict, row_idx: int, alt: bool = False):
        """Render one extracted-table row (checkbox, heading, counts, type/overview badges)."""
        self._at_id_map[id(t)] = t
        selected = id(t) in self._at_selected
        bg = T["SELECTED"] if selected else (T["N50"] if alt else T["BG"])
        row = tk.Frame(self._all_tables_scroll, bg=bg, height=ROW_H["default"], cursor="hand2")
        row.grid(row=row_idx, column=0, sticky="ew")
        row.grid_columnconfigure(1, weight=1)
        row.grid_propagate(False)

        # Selection checkbox (column 0) — Ctrl-click the row also toggles it.
        cb = tk.Label(row, text="☑" if selected else "☐", bg=bg,
                      fg=T["P600"] if selected else T["N400"],
                      font=(_SANS, 11), cursor="hand2")
        cb.grid(row=0, column=0, padx=(24, 4))

        # Heading (flex)
        heading = _short_heading(t)
        tk.Label(row, text=heading, bg=bg, fg=T["N700"], font=(_SANS, 11),
                 anchor="w").grid(row=0, column=1, sticky="ew", padx=(4, 4), pady=4)

        # Row count (data rows, excluding header)
        n_rows = max(0, len(t.get("rows") or []) - 1)
        tk.Label(row, text=f"{n_rows}r", bg=bg, fg=T["N400"],
                 font=(_SANS, 9)).grid(row=0, column=2, padx=4)

        # Type badge — effective type (matches the segment + the consolidation input)
        type_int = effective_table_type(t)
        type_name = _TYPE_LABELS.get(type_int, "Other")
        bstyle = BADGE["type"].get(type_name, BADGE["type"]["Other"])
        type_badge = tk.Label(row, text=type_name, bg=bstyle["bg"], fg=bstyle["fg"],
            font=(_SANS, 9), padx=6, pady=1)
        type_badge.grid(row=0, column=3, padx=4, pady=6)

        # In-OVERVIEW badge
        ov_status = _in_overview_status(t)
        ov_cfg = BADGE["in_overview"][ov_status]
        ov_badge = tk.Label(row, text=ov_cfg["glyph"], fg=ov_cfg["color"],
            bg=bg, font=(_SANS, 10), padx=6)
        ov_badge.grid(row=0, column=4, padx=(0, 8))

        def _toggle_sel(_e=None):
            """Checkbox / Ctrl-click handler: toggle this row's bulk selection."""
            self._at_toggle_select(t)
            return "break"

        cb.bind("<Button-1>", _toggle_sel)
        for w in (row, *row.winfo_children()):
            if w is cb:
                continue
            w.bind("<Button-1>", lambda _, tbl=t: self._preview_table(tbl))
            w.bind("<Control-Button-1>", _toggle_sel)
            w.bind("<Button-3>", lambda e, tbl=t, rw=row, tb=type_badge, ob=ov_badge:
                   self._show_table_ctx(e, tbl, rw, tb, ob))

    def _show_table_ctx(self, event, t: dict, row_widget, type_badge, ov_badge):
        """Right-click menu for a table (preview, set type, include/exclude, open PDF)."""
        menu = tk.Menu(self, tearoff=0, bg=T["BG"], fg=T["N700"],
                       activebackground=T["P100"], activeforeground=T["N900"],
                       relief="flat", font=(_SANS, 10))
        menu.add_command(label="Preview", command=lambda: self._preview_table(t))
        menu.add_separator()
        rcl = tk.Menu(menu, tearoff=0, bg=T["BG"], fg=T["N700"],
                      activebackground=T["P100"], activeforeground=T["N900"],
                      relief="flat", font=(_SANS, 10))
        for type_int, type_label in _TYPE_LABELS.items():
            check = "✓ " if effective_table_type(t) == type_int else "   "
            rcl.add_command(label=f"{check}{type_label}",
                command=lambda ti=type_int, tl=type_label, tb=type_badge, ob=ov_badge:
                        self._reclassify_table(t, ti, tl, tb, ob))
        menu.add_cascade(label="Reclassify", menu=rcl)

        currently_excluded = t.get("_include_in_overview") is False
        toggle_label = "Include in OVERVIEW" if currently_excluded else "Exclude from OVERVIEW"
        menu.add_command(label=toggle_label,
            command=lambda: self._toggle_ov_include(t, ov_badge))

        menu.add_command(label="Add note…", state="disabled")  # Phase 5
        menu.add_separator()
        pdf = t.get("_pdf_path", t.get("pdf_path", ""))
        if pdf:
            menu.add_command(label="Open PDF", command=lambda: self._open_pdf(pdf))
        else:
            menu.add_command(label="Open PDF", state="disabled")

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _reclassify_table(self, t: dict, new_type_int: int, new_type_label: str,
                           type_badge, ov_badge):
        """Re-classify one table, persist the override + feedback bundle, recompute overview."""
        old_type = t.get("type", 99)
        t["type"] = new_type_int
        t["_override_applied"] = True
        t["_override_old_type"] = old_type

        bstyle = BADGE["type"].get(new_type_label, BADGE["type"]["Other"])
        try:
            type_badge.configure(bg=bstyle["bg"], fg=bstyle["fg"], text=new_type_label)
            ov_status = _in_overview_status(t)
            ov_cfg = BADGE["in_overview"][ov_status]
            ov_badge.configure(text=ov_cfg["glyph"], fg=ov_cfg["color"])
        except Exception:
            pass

        co = self._active_company or {}
        co_norm = self._active_co_norm()
        include = t.get("_include_in_overview", True) is not False
        record = make_override_record(
            t, co_norm, new_type_label, include,
            note=f"reclassified from {old_type} via GUI")
        save_table_override(record)

        all_tables = co.get("all_tables", [])
        src_pdf = t.get("_pdf_path", t.get("pdf_path", ""))
        bundle_info = (t, src_pdf, record) if src_pdf else None
        self._worker.send("recompute_overview",
                          (co.get("id", ""), all_tables, bundle_info,
                           self._active_row_merges()))
        # Move the row into its new segment immediately.
        if self._canvas_state == "all_tables":
            self._refresh_all_tables()

    def _toggle_ov_include(self, t: dict, ov_badge):
        """Include/exclude one table from its consolidation; persist and recompute."""
        currently = t.get("_include_in_overview", True)
        new_include = not (currently is not False)
        t["_include_in_overview"] = new_include
        ov_status = _in_overview_status(t)
        ov_cfg = BADGE["in_overview"][ov_status]
        try:
            ov_badge.configure(text=ov_cfg["glyph"], fg=ov_cfg["color"])
        except Exception:
            pass
        co = self._active_company or {}
        # Persist so the exclude survives re-extraction (the learning loop).
        type_label = _TYPE_LABELS.get(t.get("type", 99), "Other")
        save_table_override(make_override_record(
            t, self._active_co_norm(), type_label, new_include,
            note="overview include toggled via GUI"))
        all_tables = co.get("all_tables", [])
        self._worker.send("recompute_overview",
                          (co.get("id", ""), all_tables, None,
                           self._active_row_merges()))

    # ── Review chips ──────────────────────────────────────────────────────────

    def _update_review_chips(self):
        """Update the status-track review chips from the active company's review counts."""
        co = self._active_company or {}
        n_li = len(co.get("review_line_items", []))
        n_tbl = sum(1 for t in co.get("all_tables", []) if t.get("type", 99) == 99)
        if n_li > 0:
            self._li_review_chip.configure(text=f"⚠ {n_li} items")
            self._li_review_chip.pack(side="left", padx=(0, 4))
        else:
            self._li_review_chip.pack_forget()
        if n_tbl > 0:
            self._tbl_review_chip.configure(text=f"▸ {n_tbl} tables")
            self._tbl_review_chip.pack(side="left", padx=(0, 4))
        else:
            self._tbl_review_chip.pack_forget()

    # ── Treeview styling ──────────────────────────────────────────────────────

    def _style_treeview(self):
        """Apply theme tokens + row tags (header/subtotal/line/alt) to the grid Treeview."""
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("Treeview",
                     background=T["BG"],
                     foreground=T["N900"],
                     rowheight=ROW_H["dense"],
                     fieldbackground=T["BG"],
                     font=(_SANS, 11),
                     borderwidth=0)
        s.configure("Treeview.Heading",
                     background=T["N100"],
                     foreground=T["N900"],
                     font=(_SANS, 11, "bold"),
                     relief="flat")
        s.map("Treeview",
              background=[("selected", T["P100"])],
              foreground=[("selected", T["N900"])])
        for sb in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            s.configure(sb, background=T["N100"],
                         troughcolor=T["RAIL"], arrowcolor=T["N400"])

        if self._tree:
            self._tree.tag_configure(
                "section_header",
                font=(_SANS, 11, "bold"),
                background=T["N100"],
                foreground=T["N900"])
            self._tree.tag_configure(
                "line_item",
                font=(_SANS, 11),
                background=T["BG"],
                foreground=T["N900"])
            self._tree.tag_configure(
                "line_item_alt",
                font=(_SANS, 11),
                background=T["N50"],
                foreground=T["N900"])
            self._tree.tag_configure(
                "subtotal",
                font=(_SANS, 11, "bold"),
                background=T["N100"],
                foreground=T["N900"])
            self._tree.tag_configure(
                "grand_total",
                font=(_SANS, 12, "bold"),
                background=T["N200"],
                foreground=T["N900"])

    # ── Financial grid ────────────────────────────────────────────────────────

    def _get_overview_table(self, stmt_type: int) -> Optional[dict]:
        """Return the consolidated table for a statement type, or None."""
        ov = (self._active_company or {}).get("overview_tables", [])
        for t in ov:
            if _overview_stmt_type(t) == stmt_type:
                return t
        return None

    def _draw_financial_grid(self, stmt_type: int):
        """Render one statement's consolidated grid into the Treeview.

        Builds three fixed meta columns (Source Label(s), Canonical, std_id - the
        last hidden unless enabled) plus one column per fiscal year. Row style
        (section header / subtotal / line) comes from the HGB mapping; negatives
        show in parentheses. A year-header click opens the source picker; a value
        cell opens the audit rail.
        """
        self._active_inner_tab = stmt_type
        self._update_inner_tab_style()
        self._tree.delete(*self._tree.get_children())
        self._grid_row_descs = {}

        t = self._get_overview_table(stmt_type)
        if not t:
            self._tree["columns"] = ("0",)
            self._tree.column("0", width=400, anchor="w")
            self._tree.heading("0", text="No data available for this statement type")
            return

        rows  = t.get("rows", [])
        years = t.get("years", [])
        if not rows:
            return

        # 3 fixed meta columns: Source Label(s) | Canonical | std_id
        _N_META = 3
        ncols   = _N_META + len(years)
        cols    = [str(i) for i in range(ncols)]
        self._tree["columns"] = cols

        self._tree.column("0", width=200, anchor="w", stretch=True)
        self._tree.heading("0", text="Source Label(s)")
        self._tree.column("1", width=160, anchor="w", stretch=False, minwidth=100)
        self._tree.heading("1", text="Canonical")
        std_w = 80 if self._show_std_id else 0
        self._tree.column("2", width=std_w, minwidth=0, anchor="w", stretch=False)
        self._tree.heading("2", text="std_id" if self._show_std_id else "")

        unit = self._currency_unit
        for i, yr in enumerate(years):
            col_key = str(i + _N_META)
            hdr = f"{yr}  ({unit})" if unit and unit != "none" else str(yr)
            self._tree.column(col_key, width=110, anchor="e", stretch=False, minwidth=80)
            # Clicking a year header opens the source picker for this statement.
            self._tree.heading(col_key, text=hdr, command=self._open_table_picker)

        self._grid_years = list(years)

        row_source_labels = t.get("row_source_labels", [])
        ncols_data = len(years) + 1  # matches the raw rows structure

        alt = False
        for ri, row in enumerate(rows):
            if ri == 0:
                continue
            values = list(row) if row else []
            while len(values) < ncols_data:
                values.append("")
            desc = str(values[0] or "").strip()

            rtype = self._row_display_type(desc, values)

            year_cells = [self._format_value(str(v or "")) for v in values[1:]]

            if rtype == "line_item":
                # Source label: distinct raw labels across years, most-recent first
                src_entry = row_source_labels[ri - 1] if (ri - 1) < len(row_source_labels) else {}
                seen_lbl: set = set()
                distinct: list = []
                for yr in years:
                    lbl = src_entry.get(yr, "")
                    if lbl and lbl not in seen_lbl:
                        distinct.append(lbl)
                        seen_lbl.add(lbl)
                src_str = "   " + (" / ".join(distinct) if distinct else desc)

                # HGB canonical + std_id lookup
                canonical_str = ""
                std_id_str    = ""
                if _HGB_AVAILABLE and desc:
                    try:
                        res   = _hgb.lookup(desc)
                        cands = res.get("candidates", [])
                        if len(cands) == 1:
                            rec = _hgb.by_id(cands[0]["std_id"])
                            if rec:
                                canonical_str = rec.get("canonical_de", "") or rec.get("canonical_en", "")
                                std_id_str    = cands[0]["std_id"]
                    except Exception:
                        pass

                tag = "line_item_alt" if alt else "line_item"
                alt = not alt
            else:
                src_str       = desc
                canonical_str = ""
                std_id_str    = ""
                tag           = rtype
                alt           = False

            display = [src_str, canonical_str, std_id_str] + year_cells
            iid = self._tree.insert("", "end", values=display, tags=(tag,))
            self._grid_row_descs[iid] = desc

    def _row_display_type(self, desc: str, values: list) -> str:
        """Classify a row for styling (section_header / subtotal / line_item) via HGB + heuristics."""
        has_values = any(str(v or "").strip() for v in values[1:])

        if not desc and has_values:
            return "subtotal"

        if _HGB_AVAILABLE and desc:
            try:
                res   = _hgb.lookup(desc)
                cands = res.get("candidates", [])
                if len(cands) == 1:
                    rec = _hgb.by_id(cands[0]["std_id"])
                    if rec:
                        rt = rec.get("row_type", "line")
                        if rt == "subtotal": return "subtotal"
                        if rt == "memo":     return "section_header"
            except Exception:
                pass

        if desc and desc == desc.upper() and len(desc) < 30 and not has_values:
            return "section_header"

        return "line_item"

    def _format_value(self, val: str) -> str:
        """Format a cell for display (blank dashes; negatives in parentheses)."""
        v = val.strip()
        if not v or v in ("-", "–", "—"):
            return ""
        if v.startswith("(") and v.endswith(")"):
            return v
        if v.startswith("-"):
            inner = v[1:].strip()
            return f"({inner})"
        return v

    # ── Tree click → audit ────────────────────────────────────────────────────

    def _on_tree_click(self, event):
        """Cell click → open the Audit rail for that (row, year, value).

        Ignores the three meta columns and does nothing during a multi-row selection.
        """
        region = self._tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        row_id = self._tree.identify_row(event.y)
        col_id = self._tree.identify_column(event.x)
        col_idx = int(col_id.replace("#", "")) - 1
        # Columns 0-2 are Source Label(s), Canonical, std_id — not clickable for audit
        if col_idx < 3 or not row_id:
            return
        # During a multi-row selection (e.g. picking rows to merge) don't pop audit.
        if len(self._tree.selection()) > 1:
            return

        values = self._tree.item(row_id, "values")
        if not values:
            return
        # Use raw desc from side dict (avoids indented/joined source label string)
        desc     = self._grid_row_descs.get(row_id, str(values[0]).strip())
        year_idx = col_idx - 3   # 3 meta columns before year columns
        years    = getattr(self, "_grid_years", [])
        year     = years[year_idx] if year_idx < len(years) else None
        cell_val = str(values[col_idx]) if col_idx < len(values) else ""

        source_doc   = None
        source_table = None
        co = self._active_company or {}
        if year:
            for sec in co.get("doc_sections", []):
                doc    = sec["doc"]
                fy_str = str(doc.get("fy", "")).replace("FY", "")
                if str(year) in fy_str:
                    source_doc = doc
                    for tbl in sec["tables"]:
                        if effective_table_type(tbl) == self._active_inner_tab:
                            source_table = tbl
                            break
                    break

        audit_data = {
            "desc":         desc,
            "value":        cell_val,
            "year":         year,
            "source_doc":   source_doc,
            "source_table": source_table,
        }
        self._open_right_rail("audit", audit_data)

    # ── Right rail ────────────────────────────────────────────────────────────

    def _open_right_rail(self, mode: str, data: dict = None):
        """Open the right rail in one of four modes: audit / preview / picker / review.

        Fully clears previous content first (CTkFrame subclasses tk.Frame, so a
        naive isinstance filter would leave old panels stacked) and rewires
        mouse-wheel scrolling. Preview gets a roomy layout - the left rail collapses
        and the rail widens to ~600 px; other modes keep 320 px.
        """
        self._rail_mode = mode
        # Preview gets a roomy panel: collapse the left company rail (you don't
        # need the company list while inspecting one table) and widen the rail.
        if mode == "preview":
            self._left_rail.grid_remove()
            self.grid_columnconfigure(0, minsize=0)
            self.grid_columnconfigure(2, minsize=max(LAYOUT["right_rail_w"], 600))
        else:
            self._left_rail.grid()
            self.grid_columnconfigure(0, minsize=LAYOUT["left_rail_w"])
            self.grid_columnconfigure(2, minsize=LAYOUT["right_rail_w"])
        self._right_rail.grid(row=2, column=2, sticky="nsew")
        # Clear previous panel content. NOTE: CTkFrame subclasses tk.Frame, so an
        # isinstance(tk.Frame) test would keep every header/scroll body and they
        # would stack. Destroy everything except the persistent border line.
        for w in self._right_rail.winfo_children():
            if w is not getattr(self, "_right_rail_border", None):
                w.destroy()

        hdr = ctk.CTkFrame(self._right_rail, fg_color=T["RAIL"], corner_radius=0)
        hdr.pack(fill="x", side="top")
        co = self._active_company or {}
        review_items = co.get("review_line_items", [])
        if mode == "audit":
            title_text = "Audit"
        elif mode == "preview":
            title_text = _short_heading(data) if data else "Preview"
        elif mode == "picker":
            title_text = f"Sources — {_TYPE_LABELS.get(self._active_inner_tab, '')}"
        else:
            title_text = f"Needs Review ({len(review_items)})"
        ctk.CTkLabel(hdr, text=title_text, font=F_H2,
                     text_color=T["N900"], anchor="w").pack(side="left", padx=(16, 0), pady=8)
        ctk.CTkButton(hdr, text="✕", width=28, height=28,
                      font=(_SANS, 11), corner_radius=R_SM,
                      fg_color="transparent", hover_color=T["N100"],
                      text_color=T["N600"],
                      command=self._close_right_rail).pack(side="right", padx=8, pady=8)

        tk.Frame(self._right_rail, bg=T["N200"], height=1).pack(fill="x")

        scroll = ctk.CTkScrollableFrame(self._right_rail, fg_color="transparent",
                                         scrollbar_button_color=T["N200"],
                                         corner_radius=0)
        scroll.pack(fill="both", expand=True)
        scroll.grid_columnconfigure(0, weight=1)

        if mode == "audit":
            self._build_audit_content(scroll, data or {})
        elif mode == "preview":
            self._build_preview_content(scroll, data or {})
        elif mode == "picker":
            self._build_picker_content(scroll)
        else:
            self._build_review_content(scroll)

        # CTkScrollableFrame only binds the wheel to its own canvas, not to the
        # child widgets that fill it — so without this the panel looks frozen.
        self._enable_mousewheel(scroll)

    def _enable_mousewheel(self, scroll_frame):
        """Recursively route <MouseWheel> from every descendant of a
        CTkScrollableFrame to that frame's internal canvas, so the wheel works
        no matter what the cursor is hovering over."""
        canvas = getattr(scroll_frame, "_parent_canvas", None)
        if canvas is None:
            return

        def _on_wheel(event):
            """Route a mouse-wheel event to the scrollable frame's canvas."""
            try:
                if event.num == 5 or event.delta < 0:
                    canvas.yview_scroll(1, "units")
                elif event.num == 4 or event.delta > 0:
                    canvas.yview_scroll(-1, "units")
            except Exception:
                pass
            return "break"

        def _bind(widget):
            # Don't hijack the wheel from a Treeview — it scrolls its own rows.
            """Recursively bind wheel scrolling on a widget subtree (skips Treeviews)."""
            if not isinstance(widget, ttk.Treeview):
                try:
                    widget.bind("<MouseWheel>", _on_wheel, add="+")
                    widget.bind("<Button-4>",   _on_wheel, add="+")
                    widget.bind("<Button-5>",   _on_wheel, add="+")
                except Exception:
                    pass
            for child in widget.winfo_children():
                _bind(child)

        _bind(scroll_frame)

    def _close_right_rail(self):
        """Hide the right rail and restore the normal 3-column layout."""
        self._rail_mode = None
        self._right_rail.grid_remove()
        self.grid_columnconfigure(2, minsize=0)
        # Restore the left company rail in case preview had collapsed it.
        self._left_rail.grid()
        self.grid_columnconfigure(0, minsize=LAYOUT["left_rail_w"])

    def _preview_table(self, t: dict):
        """Open a table in the roomy Preview rail."""
        self._open_right_rail("preview", t)

    # ── Consolidation source picker ───────────────────────────────────────────

    def _open_table_picker(self):
        """Open the right rail listing every table that feeds (or could feed)
        the OVERVIEW for the active statement type, so the user can include or
        exclude individual tables from the consolidation."""
        if not self._active_company:
            return
        self._open_right_rail("picker")

    def _candidate_tables(self, stmt_type: int) -> list:
        """Tables whose effective type matches a statement (consolidation candidates)."""
        co = self._active_company or {}
        return [t for t in co.get("all_tables", [])
                if not t.get("multi_year") and effective_table_type(t) == stmt_type]

    def _build_picker_content(self, parent):
        """Build the Sources picker: an include/exclude switch per candidate table."""
        stmt_type = self._active_inner_tab
        cands = self._candidate_tables(stmt_type)

        tk.Label(parent,
                 text="Tick the tables that should feed this consolidated view.\n"
                      "Changes are saved and re-applied on the next extraction.",
                 bg=T["RAIL"], fg=T["N500"], font=(_SANS, 9), justify="left",
                 anchor="w", wraplength=290).grid(sticky="ew", padx=14, pady=(10, 6))

        if not cands:
            tk.Label(parent, text="No tables of this type were found.",
                     bg=T["RAIL"], fg=T["N400"], font=(_SANS, 10)).grid(
                padx=14, pady=20)
            return

        for t in cands:
            included = t.get("_include_in_overview", True) is not False
            card = ctk.CTkFrame(parent, fg_color=T["N0"], corner_radius=R_SM)
            card.grid(sticky="ew", padx=10, pady=3)
            card.grid_columnconfigure(1, weight=1)

            var = tk.BooleanVar(value=included)
            ctk.CTkSwitch(card, text="", width=42, variable=var,
                          onvalue=True, offvalue=False, progress_color=T["P600"],
                          command=lambda tt=t, vv=var: self._picker_toggle(tt, vv)).grid(
                row=0, column=0, rowspan=2, padx=(10, 8), pady=10)

            heading = _short_heading(t) or t.get("heading", "") or "(untitled table)"
            ctk.CTkLabel(card, text=heading, font=F_SM, text_color=T["N900"],
                         anchor="w", wraplength=180, justify="left").grid(
                row=0, column=1, sticky="ew", padx=(0, 6), pady=(8, 0))

            yrs = self._table_years(t)
            n_rows = max(len(t.get("rows", [])) - 1, 0)
            ps, pe = t.get("page_start", ""), t.get("page_end", "")
            pg = (f"p.{ps}" if ps == pe else f"p.{ps}-{pe}") if ps or pe else ""
            meta_bits = [b for b in [t.get("doc_label", ""),
                                     (" / ".join(str(y) for y in yrs) if yrs else ""),
                                     pg, f"{n_rows} rows"] if b]
            ctk.CTkLabel(card, text="   ·   ".join(meta_bits), font=(_SANS, 9),
                         text_color=T["N500"], anchor="w").grid(
                row=1, column=1, sticky="ew", padx=(0, 6), pady=(0, 4))

            ctk.CTkButton(card, text="Preview", width=64, height=24,
                          font=F_XS, corner_radius=R_SM,
                          fg_color=T["P100"], text_color=T["P600"],
                          hover_color=T["N100"],
                          command=lambda tt=t: self._preview_table(tt)).grid(
                row=0, column=2, rowspan=2, padx=(0, 10))

    def _table_years(self, t: dict) -> list:
        """Best-effort list of fiscal years a table covers, from its header cells."""
        import re as _re
        rows = t.get("rows") or []
        if not rows:
            return []
        yrs = []
        for cell in rows[0][1:] if rows[0] else []:
            m = _re.search(r"\b(19|20)\d{2}\b", str(cell or ""))
            if m and m.group() not in yrs:
                yrs.append(m.group())
        return yrs

    def _picker_toggle(self, t: dict, var):
        """Toggle one table's consolidation membership; persist, rebuild, redraw, auto-save."""
        new_include = bool(var.get())
        t["_include_in_overview"] = new_include
        type_label = _TYPE_LABELS.get(t.get("type", 99), "Other")
        try:
            save_table_override(make_override_record(
                t, self._active_co_norm(), type_label, new_include,
                note="overview source toggled via picker"))
        except Exception:
            pass
        # Rebuild synchronously so the grid behind the panel updates immediately.
        self._rebuild_overview()
        self._draw_financial_grid(self._active_inner_tab)
        self._save_active_to_library()

    # ── OVERVIEW context menu (sources + row merge) ───────────────────────────

    def _show_overview_ctx(self, event):
        """Right-click menu on the OVERVIEW grid (edit sources, merge / unmerge rows)."""
        if not self._active_company:
            return
        # Right-click selects the row under the cursor if it's not already in the
        # selection, so single right-clicks behave intuitively.
        clicked = self._tree.identify_row(event.y)
        if clicked and clicked not in self._tree.selection():
            self._tree.selection_set(clicked)

        sel = self._tree.selection()
        data_sel = [iid for iid in sel
                    if self._grid_row_descs.get(iid, "").strip()]

        menu = tk.Menu(self, tearoff=0, bg=T["N0"], fg=T["N900"],
                       activebackground=T["P100"], activeforeground=T["N900"],
                       font=(_SANS, 10), bd=1, relief="solid")
        menu.add_command(label="Edit consolidation sources…",
                         command=self._open_table_picker)

        if len(data_sel) >= 2:
            sub = tk.Menu(menu, tearoff=0, bg=T["N0"], fg=T["N900"],
                          activebackground=T["P100"], font=(_SANS, 10))
            for iid in data_sel:
                lbl = self._grid_row_descs.get(iid, "").strip()
                sub.add_command(label=(lbl[:48] or "(row)"),
                                command=lambda tgt=iid: self._merge_selected_rows(data_sel, tgt))
            menu.add_cascade(label=f"Merge {len(data_sel)} rows — keep name…", menu=sub)
        else:
            menu.add_command(label="Merge rows  (select 2+ first)", state="disabled")

        if data_sel and self._active_row_merges():
            menu.add_command(label="Unmerge selected row(s)",
                             command=lambda: self._unmerge_rows(data_sel))

        menu.add_separator()
        menu.add_command(label="Add note…", state="disabled")  # Phase 5
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _merge_selected_rows(self, iids: list, target_iid: str):
        """Collapse the selected rows onto target_iid's row (keep its label)."""
        target_desc = self._grid_row_descs.get(target_iid, "").strip()
        if not target_desc:
            return
        co_norm = self._active_co_norm()
        n = 0
        for iid in iids:
            if iid == target_iid:
                continue
            member_desc = self._grid_row_descs.get(iid, "").strip()
            if member_desc and member_desc != target_desc:
                if save_row_merge(co_norm, member_desc, target_desc,
                                  display_label=target_desc,
                                  note="merged via overview ctx"):
                    n += 1
        if n:
            self._refresh_grid()

    def _unmerge_rows(self, iids: list):
        """Dissolve the row-merges the selected grid rows participate in, then rebuild."""
        co_norm = self._active_co_norm()
        changed = False
        for iid in iids:
            desc = self._grid_row_descs.get(iid, "").strip()
            if desc and clear_row_merges(co_norm, desc):
                changed = True
        if changed:
            self._refresh_grid()

    def _build_preview_content(self, parent, t: dict):
        """Render a raw table read-only inside the Preview rail."""
        type_int  = t.get("type", 99)
        type_name = _TYPE_LABELS.get(type_int, "Other")
        doc_label = t.get("doc_label", "")
        rows      = t.get("rows") or []

        # Type badge + filing label
        meta = tk.Frame(parent, bg=T["RAIL"])
        meta.grid(sticky="ew", padx=14, pady=(10, 8))
        bstyle = BADGE["type"].get(type_name, BADGE["type"]["Other"])
        tk.Label(meta, text=type_name, bg=bstyle["bg"], fg=bstyle["fg"],
                 font=(_SANS, 9), padx=6, pady=2).pack(side="left")
        if doc_label:
            tk.Label(meta, text=doc_label, bg=T["RAIL"], fg=T["N500"],
                     font=(_SANS, 9), padx=8).pack(side="left")

        if not rows:
            tk.Label(parent, text="No data available.", bg=T["RAIL"],
                     fg=T["N400"], font=(_SANS, 10)).grid(padx=14, pady=20)
            return

        # Determine column count from widest row
        n_cols = max(len(r) for r in rows)
        if n_cols == 0:
            return

        # Header row (row 0) used for column labels
        hdr_row = [str(v or "") for v in rows[0]]
        while len(hdr_row) < n_cols:
            hdr_row.append("")

        cols = [str(i) for i in range(n_cols)]

        # Treeview frame (no internal scroll — parent CTkScrollableFrame scrolls)
        tree_wrap = tk.Frame(parent, bg=T["N200"], bd=0)
        tree_wrap.grid(sticky="ew", padx=0, pady=0)
        tree_wrap.grid_columnconfigure(0, weight=1)

        n_data_rows = len(rows) - 1
        tree_h = min(max(n_data_rows, 4), 30)  # clamp 4–30 visible rows

        tree = ttk.Treeview(tree_wrap, columns=cols, show="headings",
                            selectmode="none", height=tree_h)
        tree.grid(row=0, column=0, sticky="ew")
        vs = ttk.Scrollbar(tree_wrap, orient="vertical", command=tree.yview)
        vs.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=vs.set)

        # Column widths — description col wider, value cols narrower
        desc_w = 240 if n_cols > 1 else 320
        tree.column("0", width=desc_w, anchor="w", stretch=True)
        tree.heading("0", text=hdr_row[0] or "Description")
        for i in range(1, n_cols):
            tree.column(str(i), width=72, anchor="e", stretch=False, minwidth=60)
            tree.heading(str(i), text=hdr_row[i][:10] if i < len(hdr_row) else str(i))

        # Tags
        tree.tag_configure("sec_hdr",  background=T["N100"], font=(_SANS, 10, "bold"))
        tree.tag_configure("subtotal", background=T["N100"], font=(_SANS, 10, "bold"))
        tree.tag_configure("normal",   background=T["BG"],   font=(_SANS, 10))
        tree.tag_configure("alt",      background=T["N50"],  font=(_SANS, 10))

        alt = False
        for ri, row in enumerate(rows[1:], 1):
            vals = [str(v or "").strip() for v in row]
            while len(vals) < n_cols:
                vals.append("")
            desc     = vals[0]
            has_vals = any(v for v in vals[1:])

            if desc and desc == desc.upper() and len(desc) < 45 and not has_vals:
                tag = "sec_hdr"
                alt = False
            elif not desc and has_vals:
                tag = "subtotal"
                alt = False
            else:
                tag = "alt" if alt else "normal"
                if desc:
                    alt = not alt

            # Format numeric cells
            display = [vals[0]] + [self._format_value(v) for v in vals[1:]]
            tree.insert("", "end", values=display, tags=(tag,))

        # Open PDF shortcut
        pdf = t.get("_pdf_path", t.get("pdf_path", ""))
        if pdf:
            ctk.CTkButton(parent, text="Open PDF", height=26, width=88,
                          font=F_XS, corner_radius=RADIUS["sm"],
                          fg_color=T["P100"], text_color=T["P600"],
                          hover_color=T["P50"],
                          command=lambda: self._open_pdf(pdf)
                          ).grid(sticky="w", padx=14, pady=(8, 4))

    def _build_audit_content(self, parent, data: dict):
        """Render the Audit rail for a cell: raw label, value, HGB mapping, source filing."""
        desc       = data.get("desc", "")
        cell_val   = data.get("value", "")
        year       = data.get("year", "")
        source_doc = data.get("source_doc") or {}
        src_table  = data.get("source_table") or {}

        def _section(text):
            """Render a small section caption inside the audit panel."""
            tk.Label(parent, text=text, bg=T["RAIL"],
                     fg=T["N400"], font=(_SANS, 8, "bold")).grid(
                sticky="w", padx=14, pady=(12, 2))

        def _card(child_fn):
            """Render a card container inside the audit panel."""
            card = ctk.CTkFrame(parent, fg_color=T["N0"],
                                 corner_radius=R_SM)
            card.grid(sticky="ew", padx=10, pady=2)
            card.grid_columnconfigure(0, weight=1)
            child_fn(card)
            return card

        _section("RAW LABEL")
        def _raw(c):
            """Render the RAW LABEL card."""
            ctk.CTkLabel(c, text=desc or "(empty)", font=F_BODY,
                         text_color=T["N900"], anchor="w",
                         wraplength=300).grid(sticky="ew", padx=12, pady=8)
        _card(_raw)

        if cell_val:
            _section("VALUE")
            def _val(c):
                """Render the VALUE card."""
                ctk.CTkLabel(c, text=cell_val, font=F_MONO,
                             text_color=T["N900"], anchor="e").grid(sticky="ew", padx=12, pady=8)
            _card(_val)

        _section("HGB MAPPING")
        mapping = self._get_audit_mapping(desc)
        mt       = mapping.get("match_type", "none")
        cands    = mapping.get("candidates", [])

        conf_color = T["success"] if mt in ("exact", "normalized") else \
                     T["warning"] if mt == "substring" else T["error"]
        conf_text  = "High confidence" if mt in ("exact", "normalized") else \
                     "Medium confidence" if mt == "substring" else "No match"

        if len(cands) == 1:
            rec = cands[0]
            def _mapping_card(c):
                """Render the single-match HGB mapping card (std_id, canonical, confidence dot)."""
                ctk.CTkLabel(c, text=rec.get("std_id", "—"),
                             font=F_H2, text_color=T["P600"], anchor="w").grid(
                    sticky="ew", padx=12, pady=(8, 2))
                ctk.CTkLabel(c, text=rec.get("canonical_en", ""),
                             font=F_SM, text_color=T["N900"], anchor="w",
                             wraplength=300).grid(sticky="ew", padx=12, pady=(0, 2))
                dot_row = ctk.CTkFrame(c, fg_color="transparent")
                dot_row.grid(sticky="w", padx=12, pady=(0, 8))
                tk.Label(dot_row, text="●", bg=T["N0"],
                         fg=conf_color, font=(_SANS, 9)).pack(side="left")
                tk.Label(dot_row, text=f"  {conf_text}", bg=T["N0"],
                         fg=T["N600"], font=(_SANS, 9)).pack(side="left")
            _card(_mapping_card)
        elif len(cands) > 1:
            def _ambig(c):
                """Render the ambiguous-mapping card (candidates each with a Remap button)."""
                ctk.CTkLabel(c, text="Ambiguous — multiple candidates:",
                             font=F_XS, text_color=T["warning"], anchor="w").grid(
                    sticky="ew", padx=12, pady=(8, 4))
                for cand in cands[:4]:
                    row = ctk.CTkFrame(c, fg_color="transparent")
                    row.grid(sticky="ew", padx=8, pady=2)
                    row.grid_columnconfigure(0, weight=1)
                    ctk.CTkLabel(row, text=f"{cand['std_id']}  {cand.get('canonical_en','')}",
                                 font=F_XS, text_color=T["N900"], anchor="w").grid(
                        row=0, column=0, sticky="w")
                    ctk.CTkButton(row, text="Remap", width=60, height=22,
                                  font=F_XS, corner_radius=R_SM,
                                  fg_color=T["P100"], text_color=T["P600"],
                                  hover_color=T["N100"],
                                  command=lambda sid=cand["std_id"],
                                                 co=source_doc.get("company", ""):
                                  self._remap_label(desc, sid, co)).grid(
                        row=0, column=1, padx=(4, 0))
                ctk.CTkFrame(c, fg_color="transparent", height=6).grid()
            _card(_ambig)
        else:
            def _no_match(c):
                """Render the 'no HGB match' card."""
                ctk.CTkLabel(c, text="No HGB match found",
                             font=F_SM, text_color=T["N400"], anchor="w").grid(
                    sticky="ew", padx=12, pady=8)
            _card(_no_match)

        _section("SOURCE")
        company   = source_doc.get("company", "—")
        fy        = source_doc.get("fy",       "—")
        doc_type  = source_doc.get("doc_type", "")
        filed     = source_doc.get("date_filed", "")
        pdf_path  = source_doc.get("pdf_path",  "")
        page_s    = src_table.get("page_start", "")
        page_e    = src_table.get("page_end",   "")
        pages_str = f"p. {page_s}" if page_s == page_e else \
                    f"p. {page_s}–{page_e}" if page_s and page_e else ""

        def _source(c):
            """Render the SOURCE card (company, year, page range, Open PDF)."""
            for line in filter(None, [company, f"{fy}  ·  {doc_type}" if doc_type else fy,
                                       filed, pages_str]):
                ctk.CTkLabel(c, text=line, font=F_SM, text_color=T["N900"],
                             anchor="w", wraplength=300).grid(sticky="ew", padx=12, pady=1)
            if pdf_path:
                ctk.CTkButton(c, text="Open PDF", height=28, width=90,
                              font=F_XS, corner_radius=R_SM,
                              fg_color=T["P100"], text_color=T["P600"],
                              hover_color=T["N100"],
                              command=lambda: self._open_pdf(pdf_path)).grid(
                    sticky="w", padx=12, pady=(6, 8))
            else:
                ctk.CTkFrame(c, fg_color="transparent", height=4).grid()
        _card(_source)

    def _build_review_content(self, parent):
        """Build the Needs Review rail: unmapped / ambiguous labels with resolve actions."""
        co = self._active_company or {}
        review_list = co.get("review_line_items", [])
        if not review_list:
            ctk.CTkLabel(parent, text="✓  All labels resolved",
                         font=F_H2, text_color=T["success"]).grid(
                padx=20, pady=40)
            return

        for item in review_list:
            raw   = item.get("raw_label", "")
            mt    = item.get("match_type", "none")
            cands = item.get("candidates", [])
            company = item.get("company", "")

            card = ctk.CTkFrame(parent, fg_color=T["N0"], corner_radius=R_SM)
            card.grid(sticky="ew", padx=10, pady=4)
            card.grid_columnconfigure(0, weight=1)

            hrow = ctk.CTkFrame(card, fg_color="transparent")
            hrow.grid(sticky="ew", padx=10, pady=(8, 2))
            hrow.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(hrow, text=raw, font=F_SM, text_color=T["N900"],
                         anchor="w", wraplength=260).grid(row=0, column=0, sticky="w")
            badge_bg    = T["warning50"]
            badge_fg    = T["warning700"]
            badge_text  = "ambiguous" if len(cands) > 1 else "no match"
            tk.Label(hrow, text=badge_text, bg=badge_bg, fg=badge_fg,
                     font=(_SANS, 8), padx=4).grid(row=0, column=1, padx=(4, 0))

            for cand in cands[:3]:
                btn_row = ctk.CTkFrame(card, fg_color="transparent")
                btn_row.grid(sticky="ew", padx=10, pady=2)
                btn_row.grid_columnconfigure(0, weight=1)
                ctk.CTkLabel(btn_row,
                             text=f"{cand['std_id']}  {cand.get('canonical_en', '')}",
                             font=F_XS, text_color=T["N600"], anchor="w").grid(
                    row=0, column=0, sticky="w")
                ctk.CTkButton(btn_row, text="Map", width=48, height=22,
                              font=F_XS, corner_radius=R_SM,
                              fg_color=T["P100"], text_color=T["P600"],
                              hover_color=T["N100"],
                              command=lambda r=raw, s=cand["std_id"], c=company:
                              self._resolve_review(r, s, c)).grid(
                    row=0, column=1, padx=(4, 0))

            actions = ctk.CTkFrame(card, fg_color="transparent")
            actions.grid(sticky="ew", padx=10, pady=(4, 8))

            ctk.CTkButton(actions, text="Skip", width=50, height=24,
                          font=F_XS, corner_radius=R_SM,
                          fg_color="transparent", border_width=1,
                          border_color=T["N200"], text_color=T["N400"],
                          hover_color=T["N100"],
                          command=lambda r=raw: self._skip_review(r)).pack(side="left")

            if not cands:
                manual_var = tk.StringVar()
                ctk.CTkEntry(actions, textvariable=manual_var,
                             placeholder_text="std_id…", width=90, height=24,
                             font=F_XS, fg_color=T["N100"],
                             border_color=T["N200"]).pack(side="left", padx=(8, 4))
                ctk.CTkButton(actions, text="OK", width=40, height=24,
                              font=F_XS, corner_radius=R_SM,
                              fg_color=T["P600"], hover_color=T["P700"],
                              command=lambda r=raw, v=manual_var, c=company:
                              self._resolve_review_manual(r, v, c)).pack(side="left")

    # ── Needs Review ──────────────────────────────────────────────────────────

    def _compute_review_list(self) -> list:
        """Scan the active company's tables for labels that don't resolve to one HGB position."""
        if not _HGB_AVAILABLE:
            return []
        flagged = []
        seen: set = set()
        co = self._active_company or {}
        for t in co.get("all_tables", []):
            if t.get("multi_year"):
                continue
            company = t.get("_company", "")
            fy      = t.get("doc_label", "")
            for row in (t.get("rows") or [])[1:]:
                if not row:
                    continue
                desc = str(row[0] or "").strip()
                if not desc or desc in seen:
                    continue
                try:
                    res   = _hgb.lookup(desc)
                    mt    = res.get("match_type", "none")
                    cands = res.get("candidates", [])
                    if mt == "none" or len(cands) > 1:
                        seen.add(desc)
                        flagged.append({
                            "raw_label": desc,
                            "match_type": mt,
                            "candidates": cands,
                            "fy":      fy,
                            "company": company,
                        })
                except Exception:
                    pass
        return flagged

    def _toggle_review_rail(self):
        """Open / close the Needs Review rail."""
        if self._rail_mode == "review":
            self._close_right_rail()
        else:
            self._open_right_rail("review")

    def _resolve_review(self, raw_label: str, std_id: str, company: str = ""):
        """Resolve a review item to a chosen std_id (writes a client alias)."""
        self._write_alias(raw_label, std_id, company, "resolved_via_review_ui")
        co = self._active_company
        if co:
            co["review_line_items"] = [i for i in co.get("review_line_items", [])
                                        if i["raw_label"] != raw_label]
        self._update_review_chips()
        self._refresh_grid()
        if self._rail_mode == "review":
            self._open_right_rail("review")

    def _resolve_review_manual(self, raw_label: str, var: tk.StringVar,
                                company: str = ""):
        """Resolve a review item using a manually typed, validated std_id."""
        std_id = var.get().strip()
        if not std_id:
            return
        if _HGB_AVAILABLE:
            try:
                rec = _hgb.by_id(std_id)
                if not rec:
                    messagebox.showwarning("Unknown std_id",
                                           f"'{std_id}' not found in HGB map.")
                    return
            except Exception:
                pass
        self._resolve_review(raw_label, std_id, company)

    def _skip_review(self, raw_label: str):
        """Dismiss a review item without resolving it."""
        co = self._active_company
        if co:
            co["review_line_items"] = [i for i in co.get("review_line_items", [])
                                        if i["raw_label"] != raw_label]
        self._update_review_chips()
        if self._rail_mode == "review":
            self._open_right_rail("review")

    def _remap_label(self, raw_label: str, new_std_id: str, company: str = ""):
        """Remap a label to a different std_id from the Audit panel (writes an alias)."""
        self._write_alias(raw_label, new_std_id, company, "remapped_via_audit_ui")
        self._refresh_grid()
        self._close_right_rail()

    def _write_alias(self, raw_label: str, std_id: str,
                     company: str, note: str = ""):
        """Append a label→std_id mapping to the version-controlled client alias file."""
        try:
            _ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_ALIASES_PATH, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([raw_label, std_id, company, note])
        except Exception:
            pass

    def _active_co_norm(self) -> str:
        """Normalised key of the active company (used by the override / merge stores)."""
        co = self._active_company or {}
        return _normalize_for_override_key(co.get("name", ""))

    def _active_row_merges(self) -> dict:
        """Load the active company's saved row-merges."""
        try:
            return load_row_merges(self._active_co_norm())
        except Exception:
            return {}

    def _rebuild_overview(self):
        """Recompute the active company's consolidation (synchronous; applies row-merges)."""
        co = self._active_company
        if co:
            co["overview_tables"] = build_multi_year_tables(
                co["all_tables"], row_merges=self._active_row_merges())

    def _refresh_grid(self):
        """Rebuild the consolidation, redraw the grid, and auto-save to the library."""
        self._rebuild_overview()
        self._draw_financial_grid(self._active_inner_tab)
        self._save_active_to_library()

    def _save_active_to_library(self, co: dict = None):
        """Queue a debounced library save for the given (or active) company.

        Corrections fire rapidly; serialising a multi-MB snapshot on every click
        would stall the UI. Instead coalesce to one save ~1.5s after the last
        change. The snapshot (json.dumps) runs on the main thread for a
        consistent read; the file write happens on a daemon thread.
        """
        co = co or self._active_company
        if not co or not co.get("all_tables"):
            return
        self._lib_pending_co = co
        if self._lib_save_after is not None:
            try:
                self.after_cancel(self._lib_save_after)
            except Exception:
                pass
        self._lib_save_after = self.after(1500, self._flush_library_save)

    def _flush_library_save(self):
        """Fire a queued library save: snapshot here (main thread), write off-thread."""
        self._lib_save_after = None
        co = self._lib_pending_co or self._active_company
        self._lib_pending_co = None
        if not co or not co.get("all_tables"):
            return
        try:
            prep = prepare_library_save(co)
        except Exception:
            prep = None
        if not prep:
            return
        path, text, meta = prep
        threading.Thread(target=write_library_file, args=(path, text, meta),
                         daemon=True).start()

    def _get_audit_mapping(self, desc: str) -> dict:
        """Look up a label's HGB mapping for the audit panel (safe when HGB is unavailable)."""
        if not _HGB_AVAILABLE or not desc:
            return {"match_type": "none", "candidates": []}
        try:
            return _hgb.lookup(desc)
        except Exception:
            return {"match_type": "none", "candidates": []}

    def _open_pdf(self, pdf_path: str):
        """Open a source PDF in the OS default viewer."""
        try:
            os.startfile(pdf_path)
        except Exception:
            pass

    # ── Polling + event dispatch ──────────────────────────────────────────────

    def _poll(self):
        """Drain the worker→GUI queue every 100 ms and dispatch each event."""
        while not self._gui_q.empty():
            event, data = self._gui_q.get()
            self._handle(event, data)
        drained = 0
        while not _LOG_Q.empty() and drained < 50:
            try:
                line = _LOG_Q.get_nowait()
                if self._log_visible and self._log_text:
                    self._append_log(line)
            except queue.Empty:
                break
            drained += 1
        self.after(100, self._poll)

    def _handle(self, event: str, data):
        """Route a single worker→GUI event to its handler.

        Covers the worker protocol: ready/status, search_results, batch_* (progress/
        doc_done/error/complete), overview_ready, bundle_written, exported, error.
        Batch completion rebuilds the overview, recomputes review, switches to
        OVERVIEW, enables Export, and auto-saves the company.
        """
        if event == "ready":
            self._search_btn.configure(state="normal")
            self._set_status("Ready", T["success"])
            self._set_breadcrumb("Ready to search")

        elif event == "status":
            self._set_status(data, T["warning"])

        elif event == "search_results":
            self._show_results(data)

        elif event == "need_confirm":
            self._captcha_pending = True
            self._captcha_lbl.grid()

        elif event == "batch_progress":
            prog, status_txt = data
            self._progress.configure(fg_color=T["N200"],
                                      progress_color=T["P600"])
            self._progress.set(min(1.0, max(0.0, float(prog))))
            self._set_status(status_txt, T["warning"])
            self._update_progress_card(status_txt)

        elif event == "batch_doc_done":
            doc, tables = data
            self._add_doc_section(doc, tables)

        elif event == "batch_error":
            _, label, msg = data
            self._set_status(f"⚠  {label}: {msg}", T["error"])

        elif event == "batch_complete":
            self._progress.configure(fg_color=T["STATUSBAR"],
                                      progress_color=T["STATUSBAR"])
            self._progress.set(0)
            self._captcha_lbl.grid_remove()
            self._captcha_pending = False

            co = self._active_company
            if co:
                self._rebuild_overview()
                co["review_line_items"] = self._compute_review_list()
                self._update_review_chips()
                available = {_overview_stmt_type(t) for t in co.get("overview_tables", [])}
                if available:
                    first = min(available)
                    self._switch_canvas("overview")
                    self._active_inner_tab = first
                    self._update_inner_tab_style()
                    self._draw_financial_grid(first)
                    self._export_btn.configure(state="normal")
                self._save_active_to_library(co)   # snapshot freshly extracted work
            self._refresh_company_rail()

            co = self._active_company or {}
            n = len(co.get("all_tables", []))
            self._set_status(f"✓  {n} tables extracted", T["success"])
            self._update_breadcrumb()

        elif event == "overview_ready":
            company_id, overview_tables = data
            co = next((c for c in self._session["companies"] if c["id"] == company_id), None)
            if co:
                co["overview_tables"] = overview_tables
                if (self._session["active_company_id"] == company_id
                        and self._canvas_state == "overview"):
                    self._draw_financial_grid(self._active_inner_tab)
                self._save_active_to_library(co)   # persist correction result

        elif event == "bundle_written":
            ok, path_str = data
            self._bundle_history.append((ok, path_str))
            self._bundle_history = self._bundle_history[-3:]
            any_failed = any(not s for s, _ in self._bundle_history)
            self._bundle_dot.configure(fg=T["warning"] if any_failed else T["N400"])

        elif event == "exported":
            count, path = data
            self._set_status(f"✓  Saved {count} sheet(s) → {path.name}", T["success"])
            messagebox.showinfo("Export complete",
                                f"Exported {count} sheet(s) to:\n{path}")

        elif event == "error":
            self._set_status(f"✕  {data}", T["error"])
            messagebox.showerror("Error", data)

    def _set_status(self, msg: str, colour: str = None):
        """Set the status-track message (with an optional colour)."""
        colour = colour or T["N400"]
        self._breadcrumb_lbl.configure(text=msg)
        self._status_dot.configure(fg=colour)

    def _set_breadcrumb(self, text: str):
        """Set the breadcrumb text directly."""
        self._breadcrumb_lbl.configure(text=text)

    def _update_breadcrumb(self):
        """Render 'Active: <Company> ▸ N filings ▸ <Tab>' in the status track."""
        co = self._active_company
        if not co:
            return
        name = (co.get("name") or "").split(",")[0].strip()[:28] or "—"
        n_filings = len(co.get("doc_sections", []))
        filings_str = f"{n_filings} filing{'s' if n_filings != 1 else ''}"
        if self._canvas_state == "all_tables":
            tab_str = "All Tables"
        elif self._canvas_state == "overview":
            tab_str = _STMT_NAMES.get(self._active_inner_tab, "OVERVIEW")
        else:
            tab_str = ""
        parts = [f"Active: {name}", filings_str]
        if tab_str:
            parts.append(tab_str)
        self._breadcrumb_lbl.configure(text="  ▸  ".join(parts))

    def _show_bundle_tip(self, event=None):
        """Show the bundle-dot tooltip listing the last few feedback-bundle results."""
        self._hide_bundle_tip()
        if not self._bundle_history:
            return
        lines = []
        for ok, path in self._bundle_history:
            glyph = "✓" if ok else "✗"
            name = Path(path).name if path else "—"
            lines.append(f"{glyph}  {name}")
        tip = tk.Toplevel(self)
        tip.wm_overrideredirect(True)
        tip.wm_attributes("-topmost", True)
        x = self._bundle_dot.winfo_rootx()
        y = self._bundle_dot.winfo_rooty() - 6
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(tip, text="\n".join(lines),
                 bg=T["N800"], fg=T["N100"],
                 font=(_SANS, 9), justify="left",
                 padx=8, pady=4).pack()
        self._bundle_tip = tip

    def _hide_bundle_tip(self, event=None):
        """Hide the bundle-dot tooltip."""
        if self._bundle_tip:
            try:
                self._bundle_tip.destroy()
            except Exception:
                pass
            self._bundle_tip = None

    def _inline_captcha_confirm(self):
        """Signal the worker that the user solved the inline CAPTCHA."""
        self._captcha_lbl.grid_remove()
        self._captcha_pending = False
        self._worker.confirm()

    # ── Search flow ───────────────────────────────────────────────────────────

    def _on_search(self):
        """Start a register search for the entered company name."""
        name = self._entry.get().strip()
        if len(name) < 2:
            messagebox.showwarning("Input required",
                                   "Please enter at least 2 characters.")
            return
        self._clear_results()
        self._search_btn.configure(state="disabled")
        self._set_status(f"Searching for '{name}'…", T["warning"])
        self._worker.send("search", name)

    def _clear_results(self):
        """Clear the search results model and widgets."""
        for w in self._results_frame.winfo_children():
            w.destroy()
        self._results.clear()
        self._result_vars.clear()
        self._co_expanded.clear()
        self._sel_all_var.set(False)
        self._sel_count_lbl.configure(text="0 selected")
        self._process_btn.configure(text="Process Selected  (0)",
                                     state="disabled")

    def _show_results(self, results):
        """Render the search results returned by the worker."""
        from collections import defaultdict
        self._search_btn.configure(state="normal")
        if not results:
            self._set_status("No filings found", T["error"])
            tk.Label(self._results_frame,
                     text="No filings found. Try a shorter or alternate name.",
                     bg=T["BG"], fg=T["N400"],
                     font=(_SANS, 11)).grid(padx=20, pady=20)
            return
        self._results = results
        groups: dict = defaultdict(list)
        for r in results:
            co = r["company"].split("(")[0].strip()
            groups[co].append(r)
        for co in groups:
            groups[co].sort(key=lambda r: r["fy"], reverse=True)

        row = 0
        for co, filings in groups.items():
            expanded = self._co_expanded.get(co, True)
            icon     = "▾" if expanded else "▸"
            n_co     = len(filings)
            co_hdr = ctk.CTkFrame(self._results_frame,
                                   fg_color=T["N100"], corner_radius=8,
                                   cursor="hand2")
            co_hdr.grid(row=row, column=0, sticky="ew", padx=2, pady=(4, 2))
            co_hdr.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(co_hdr, text=f"  {icon}", font=(_SANS, 11),
                         text_color=T["N600"], width=18, anchor="w").grid(
                row=0, column=0, padx=(6, 2), pady=5)
            ctk.CTkLabel(co_hdr, text=co, font=F_H2,
                         text_color=T["N900"], anchor="w").grid(
                row=0, column=1, sticky="w", pady=5)
            ctk.CTkLabel(co_hdr,
                         text=f"{n_co} filing{'s' if n_co > 1 else ''}",
                         font=F_XS, text_color=T["N400"]).grid(
                row=0, column=2, padx=(0, 8))

            def _tog(_, c=co):
                """Toggle a single result's selection."""
                self._co_expanded[c] = not self._co_expanded.get(c, True)
                self._clear_results_widgets()
                self._show_results(self._results)

            for w in (co_hdr, *co_hdr.winfo_children()):
                w.bind("<Button-1>", _tog)
            row += 1

            if expanded:
                for filing in filings:
                    idx = results.index(filing)
                    while len(self._result_vars) <= idx:
                        self._result_vars.append(tk.BooleanVar(value=False))
                    self._result_card(row, idx, filing, self._result_vars[idx])
                    row += 1

        n = len(results)
        self._set_status(f"{n} filing(s) found", T["success"])

    def _clear_results_widgets(self):
        """Destroy all rendered result-card widgets."""
        for w in self._results_frame.winfo_children():
            w.destroy()

    def _result_card(self, row: int, idx: int, r: dict, var: tk.BooleanVar):
        """Render one search-result card (checkbox + filing metadata)."""
        card = ctk.CTkFrame(self._results_frame,
                             fg_color=T["N0"], corner_radius=R_CARD,
                             cursor="hand2", border_width=1,
                             border_color=T["N200"])
        card.grid(row=row, column=0, sticky="ew", padx=2, pady=3)
        card.grid_columnconfigure(2, weight=1)

        cb = ctk.CTkCheckBox(card, text="", variable=var, width=20,
                              fg_color=T["P600"], hover_color=T["P700"],
                              command=self._update_process_count)
        cb.grid(row=0, rowspan=2, column=0, padx=(10, 4), pady=8)

        year = r["fy"].replace("FY", "")
        ctk.CTkLabel(card, text=year,
                     font=(_SANS, 22, "bold"),
                     text_color=T["P600"], width=56, anchor="center").grid(
            row=0, rowspan=2, column=1, padx=(0, 10))

        company = r["company"].split("(")[0].strip()
        ctk.CTkLabel(card, text=company, font=F_H2,
                     text_color=T["N900"], anchor="w").grid(
            row=0, column=2, sticky="w", padx=(0, 8), pady=(8, 1))
        ctk.CTkLabel(card,
                     text=f"{r['doc_type']}  ·  {r['date_filed']}",
                     font=F_XS, text_color=T["N400"], anchor="w").grid(
            row=1, column=2, sticky="w", padx=(0, 8), pady=(0, 8))

        def _toggle(_, v=var):
            """Toggle this result card's selection."""
            v.set(not v.get())
            self._update_process_count()

        for w in (card, *card.winfo_children()):
            if not isinstance(w, ctk.CTkCheckBox):
                w.bind("<Button-1>", _toggle)

    def _toggle_select_all(self):
        """Select / deselect all search results."""
        s = self._sel_all_var.get()
        for v in self._result_vars:
            v.set(s)
        self._update_process_count()

    def _update_process_count(self):
        """Update the 'Process N selected' button label and enabled state."""
        n   = sum(v.get() for v in self._result_vars)
        txt = f"Process Selected  ({n})" if n else "Process Selected  (0)"
        self._sel_count_lbl.configure(text=f"{n} selected")
        self._process_btn.configure(text=txt,
                                     state="normal" if n else "disabled")
        if self._result_vars:
            self._sel_all_var.set(n == len(self._result_vars))

    # ── Processing flow ───────────────────────────────────────────────────────

    def _on_process_selected(self):
        """Send the ticked filings to the worker for batch download + extraction."""
        selected = [r for r, v in zip(self._results, self._result_vars)
                    if v.get()]
        if not selected:
            return
        self._process_btn.configure(state="disabled")
        self._search_btn.configure(state="disabled")
        for w in self._progress_cards_frame.winfo_children():
            w.destroy()
        self._progress_cards.clear()
        self._worker.send("process_batch", (selected, self._pdf_dir))

    def _update_progress_card(self, status_txt: str):
        """Update a per-filing progress card during a batch."""
        pass   # Status track is sufficient for progress feedback

    def _add_doc_section(self, doc: dict, tables: list):
        """Append a finished filing's tables to the active company and re-apply saved overrides."""
        co = self._active_company
        if co is None:
            co = self._make_company(doc.get("company", ""))
            self._session["companies"].append(co)
            self._session["active_company_id"] = co["id"]
        if co.get("name", "(Searching…)") in ("(Searching…)", ""):
            co["name"] = doc.get("company", "").split(",")[0].strip()[:30]
        fy_key = (doc.get("company", ""), doc.get("fy", ""), doc.get("doc_type", ""))
        if any((s["doc"].get("company"), s["doc"].get("fy"), s["doc"].get("doc_type")) == fy_key
               for s in co.get("doc_sections", [])):
            return
        co["all_tables"].extend(tables)
        co["doc_sections"].append({"doc": doc, "tables": tables})
        # Re-apply any persisted overrides so a re-extraction honours saved reclassifications
        try:
            _overrides = load_table_overrides()
            _co_norm = _normalize_for_override_key(co.get("name", ""))
            apply_table_overrides(co["all_tables"], _co_norm, _overrides)
        except Exception:
            pass
        self._refresh_company_rail()

    # ── Export ────────────────────────────────────────────────────────────────

    def _on_export_excel(self):
        """Open the export options dialog (only if there is something to export)."""
        co = self._active_company or {}
        if not co.get("overview_tables") and not co.get("all_tables"):
            return
        self._open_export_dialog()

    def _open_export_dialog(self):
        """Build the modal export dialog (scope dropdown + statement toggles)."""
        dlg = ctk.CTkToplevel(self)
        dlg.title("Export options")
        dlg.geometry("440x340")
        dlg.transient(self)
        dlg.configure(fg_color=T["BG"])
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Export to Excel", font=F_H1,
                     text_color=T["N900"], anchor="w").pack(
            fill="x", padx=20, pady=(18, 4))

        # ── Scope ─────────────────────────────────────────────────────────
        ctk.CTkLabel(dlg, text="WHAT TO EXPORT", font=(_SANS, 9, "bold"),
                     text_color=T["N400"], anchor="w").pack(fill="x", padx=20, pady=(10, 2))
        scope_var = tk.StringVar(value="Everything")
        ctk.CTkOptionMenu(
            dlg, values=["Consolidation only", "Raw tables only", "Everything"],
            variable=scope_var, font=F_SM, height=34, corner_radius=R_SM,
            fg_color=T["N100"], button_color=T["P600"], button_hover_color=T["P700"],
            text_color=T["N900"]).pack(fill="x", padx=20, pady=(0, 4))

        # ── Statement toggles ─────────────────────────────────────────────
        ctk.CTkLabel(dlg, text="STATEMENTS", font=(_SANS, 9, "bold"),
                     text_color=T["N400"], anchor="w").pack(fill="x", padx=20, pady=(12, 2))
        stmt_vars = {}
        srow = ctk.CTkFrame(dlg, fg_color="transparent")
        srow.pack(fill="x", padx=18, pady=(0, 6))
        # "Other" = type 99 (Anhang/notes/raw tables with no consolidated view).
        # Default on so 'Everything'/'Raw' export the full set as before.
        for label, tp in (("Bilanz", 0), ("GuV", 1), ("Cashflow", 2), ("Other", 99)):
            v = tk.BooleanVar(value=True)
            stmt_vars[tp] = v
            ctk.CTkCheckBox(srow, text=label, variable=v, font=F_SM,
                            checkbox_width=20, checkbox_height=20,
                            fg_color=T["P600"], hover_color=T["P700"],
                            text_color=T["N900"]).pack(side="left", padx=(2, 12), pady=4)

        # ── Buttons ───────────────────────────────────────────────────────
        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(side="bottom", fill="x", padx=20, pady=16)
        ctk.CTkButton(btns, text="Cancel", height=38, width=90,
                      corner_radius=R_PILL, font=F_SM,
                      fg_color=T["N100"], text_color=T["N700"], hover_color=T["N200"],
                      command=dlg.destroy).pack(side="right", padx=(8, 0))

        def _go():
            """Validate the export selection, then launch the save + export flow."""
            sel = {tp for tp, v in stmt_vars.items() if v.get()}
            if not sel:
                messagebox.showinfo("Export", "Select at least one statement to export.",
                                    parent=dlg)
                return
            scope = scope_var.get()
            dlg.destroy()
            self._run_export(scope, sel)

        ctk.CTkButton(btns, text="Export", height=38, width=120,
                      corner_radius=R_PILL, font=(_SANS, 13, "bold"),
                      fg_color=T["P600"], hover_color=T["P700"],
                      command=_go).pack(side="right")

    def _run_export(self, scope: str, sel_types: set):
        """Filter tables by scope/statements, ask for a path, and send the export job."""
        co = self._active_company or {}
        ov_all  = co.get("overview_tables", [])
        raw_all = [t for t in co.get("all_tables", []) if not t.get("multi_year")]

        ov_filtered  = [t for t in ov_all if _overview_stmt_type(t) in sel_types]
        raw_filtered = [t for t in raw_all if effective_table_type(t) in sel_types]

        if scope == "Consolidation only":
            tables, all_tables = ov_filtered, []
        elif scope == "Raw tables only":
            tables, all_tables = [], raw_filtered
        else:  # Everything
            tables, all_tables = ov_filtered, raw_filtered

        if not tables and not all_tables:
            messagebox.showinfo("Export", "Nothing to export for the chosen options.")
            return

        doc_sections = co.get("doc_sections", [])
        result = doc_sections[0]["doc"] if doc_sections else {}
        company  = sanitize_filename(result.get("company", "export"))
        doc_type = sanitize_filename(result.get("doc_type", ""))
        fy       = result.get("fy", "")
        tag = {"Consolidation only": "consolidation",
               "Raw tables only": "raw"}.get(scope, "model")
        default  = f"{company}_{doc_type}_{fy}_{tag}.xlsx"

        out_path = filedialog.asksaveasfilename(
            title="Save Excel workbook",
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
            initialfile=default,
            initialdir=str(Path.home() / "Downloads"))
        if not out_path:
            return

        review_list = co.get("review_line_items", [])
        review_meta = [
            {"raw_label": i["raw_label"], "std_id": "", "canonical_en": "",
             "match_type":  i["match_type"], "fiscal_year": i["fy"],
             "company":     i["company"]}
            for i in review_list
        ]

        self._export_btn.configure(state="disabled")
        self._worker.send("export_v2", (
            tables,
            all_tables,
            result,
            Path(out_path),
            self._decimal_sep,
            self._thousand_sep,
            self._pdf_dir,
            review_meta,
        ))
        self._export_btn.configure(state="normal")

    # ── Settings ──────────────────────────────────────────────────────────────

    def _build_settings_panel(self):
        """Build the slide-over Settings panel (theme, currency, format, folders, columns)."""
        self._settings_open = False

        panel_shell = tk.Frame(self, bg=T["RAIL"], width=440)
        panel_shell.pack_propagate(False)
        self._settings_panel = panel_shell

        panel = ctk.CTkFrame(panel_shell, fg_color=T["RAIL"],
                              corner_radius=0,
                              border_width=1, border_color=T["N200"])
        panel.pack(fill="both", expand=True)

        hdr = ctk.CTkFrame(panel, fg_color="transparent", height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="  ⚙  Settings", font=F_H1,
                     text_color=T["N900"], anchor="w").pack(side="left", padx=12)
        ctk.CTkButton(hdr, text="✕", width=32, height=32,
                      font=(_SANS, 13), corner_radius=R_PILL,
                      fg_color="transparent", hover_color=T["N100"],
                      text_color=T["N600"],
                      command=self._close_settings).pack(
            side="right", padx=8, pady=10)

        ctk.CTkFrame(panel, fg_color=T["N200"], height=1,
                      corner_radius=0).pack(fill="x")

        scroll = ctk.CTkScrollableFrame(panel, fg_color="transparent",
                                         scrollbar_button_color=T["N200"])
        scroll.pack(fill="both", expand=True)

        def _section(title):
            """Render a settings section caption."""
            ctk.CTkLabel(scroll, text=title, font=F_LABEL,
                         text_color=T["N400"], anchor="w").pack(
                fill="x", padx=16, pady=(16, 4))

        # ── Theme ─────────────────────────────────────────────────────────
        _section("THEME")
        theme_frame = ctk.CTkFrame(scroll, fg_color=T["N0"], corner_radius=R_SM)
        theme_frame.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(theme_frame, text="Appearance", font=F_SM,
                     text_color=T["N900"], anchor="w").pack(side="left", padx=12, pady=12)
        self._theme_var = tk.StringVar(value=self._theme_name)
        theme_seg = ctk.CTkSegmentedButton(
            theme_frame, values=["Light", "Dark"],
            font=F_SM, height=36,
            selected_color=T["P600"], selected_hover_color=T["P700"],
            unselected_color=T["N100"],
            variable=self._theme_var,
            command=self._apply_theme)
        theme_seg.pack(side="right", padx=8, pady=8)

        # ── Currency unit ──────────────────────────────────────────────────
        _section("CURRENCY DISPLAY")
        cur_frame = ctk.CTkFrame(scroll, fg_color=T["N0"], corner_radius=R_SM)
        cur_frame.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(cur_frame, text="Unit in column headers",
                     font=F_SM, text_color=T["N900"], anchor="w").pack(
            side="left", padx=12, pady=12)
        self._currency_var = tk.StringVar(value=self._currency_unit)
        cur_options = [u for u in CURRENCY_UNITS]
        cur_menu = ctk.CTkOptionMenu(
            cur_frame, values=cur_options, variable=self._currency_var,
            font=F_SM, height=32, corner_radius=R_SM,
            fg_color=T["N100"], button_color=T["P600"],
            button_hover_color=T["P700"])
        cur_menu.pack(side="right", padx=8, pady=8)

        # ── Number format ──────────────────────────────────────────────────
        _section("NUMBER FORMAT")
        locale_frame = ctk.CTkFrame(scroll, fg_color=T["N0"], corner_radius=R_SM)
        locale_frame.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(locale_frame, text="Excel output format",
                     font=F_SM, text_color=T["N900"], anchor="w").pack(
            side="left", padx=12, pady=12)
        init_locale = "German" if self._decimal_sep == "," else "English"
        self._locale_var = tk.StringVar(value=init_locale)
        ctk.CTkSegmentedButton(
            locale_frame, values=["German", "English"],
            font=F_SM, height=36,
            selected_color=T["P600"], selected_hover_color=T["P700"],
            unselected_color=T["N100"],
            variable=self._locale_var).pack(side="right", padx=8, pady=8)

        # ── PDF folder ─────────────────────────────────────────────────────
        _section("PDF DOWNLOAD FOLDER")
        folder_frame = ctk.CTkFrame(scroll, fg_color=T["N0"], corner_radius=R_SM)
        folder_frame.pack(fill="x", padx=12, pady=4)
        folder_frame.grid_columnconfigure(0, weight=1)
        self._folder_var = tk.StringVar(value=str(self._pdf_dir))
        ctk.CTkEntry(folder_frame, textvariable=self._folder_var,
                     font=F_XS, fg_color=T["N0"], border_width=0,
                     text_color=T["N600"]).grid(
            row=0, column=0, sticky="ew", padx=(12, 4), pady=10)

        def _browse_pdf():
            """Pick the PDF download folder."""
            chosen = filedialog.askdirectory(title="Choose PDF download folder",
                                              initialdir=str(self._pdf_dir))
            if chosen:
                self._folder_var.set(chosen)

        ctk.CTkButton(folder_frame, text="Browse", width=72, height=28,
                      font=F_XS, corner_radius=R_SM,
                      fg_color=T["P600"], hover_color=T["P700"],
                      command=_browse_pdf).grid(row=0, column=1, padx=(0, 8))

        # ── Log folder ─────────────────────────────────────────────────────
        _section("SESSION LOG FOLDER")
        tog_frame = ctk.CTkFrame(scroll, fg_color=T["N0"], corner_radius=R_SM)
        tog_frame.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(tog_frame, text="Save PDF & Log files together",
                     font=F_SM, text_color=T["N900"], anchor="w").pack(
            side="left", padx=12, pady=10)
        self._log_together_var = tk.BooleanVar(value=self._log_together)
        ctk.CTkSwitch(tog_frame, text="", width=46,
                      variable=self._log_together_var,
                      onvalue=True, offvalue=False,
                      progress_color=T["P600"]).pack(
            side="right", padx=12, pady=10)

        log_folder_frame = ctk.CTkFrame(scroll, fg_color=T["N0"], corner_radius=R_SM)
        log_folder_frame.pack(fill="x", padx=12, pady=(2, 4))
        log_folder_frame.grid_columnconfigure(0, weight=1)
        self._log_folder_var = tk.StringVar(value=str(self._log_dir))
        ctk.CTkEntry(log_folder_frame, textvariable=self._log_folder_var,
                     font=F_XS, fg_color=T["N0"], border_width=0,
                     text_color=T["N600"]).grid(
            row=0, column=0, sticky="ew", padx=(12, 4), pady=10)

        def _browse_log():
            """Pick the session-log folder."""
            chosen = filedialog.askdirectory(title="Choose log folder",
                                              initialdir=str(self._log_dir))
            if chosen:
                self._log_folder_var.set(chosen)

        ctk.CTkButton(log_folder_frame, text="Browse", width=72, height=28,
                      font=F_XS, corner_radius=R_SM,
                      fg_color=T["P600"], hover_color=T["P700"],
                      command=_browse_log).grid(row=0, column=1, padx=(0, 8))

        del_frame = ctk.CTkFrame(scroll, fg_color=T["N0"], corner_radius=R_SM)
        del_frame.pack(fill="x", padx=12, pady=(2, 12))
        ctk.CTkLabel(del_frame, text="Delete log on close",
                     font=F_SM, text_color=T["N900"], anchor="w").pack(
            side="left", padx=12, pady=10)
        self._log_delete_var = tk.BooleanVar(value=self._log_delete)
        ctk.CTkSwitch(del_frame, text="", width=46,
                      variable=self._log_delete_var,
                      onvalue=True, offvalue=False,
                      progress_color=T["P600"]).pack(
            side="right", padx=12, pady=10)

        # ── Overview columns ───────────────────────────────────────────────
        _section("OVERVIEW COLUMNS")
        std_id_frame = ctk.CTkFrame(scroll, fg_color=T["N0"], corner_radius=R_SM)
        std_id_frame.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(std_id_frame, text="Show std_id column",
                     font=F_SM, text_color=T["N900"], anchor="w").pack(
            side="left", padx=12, pady=10)
        self._std_id_var = tk.BooleanVar(value=self._show_std_id)
        ctk.CTkSwitch(std_id_frame, text="", width=46,
                      variable=self._std_id_var,
                      onvalue=True, offvalue=False,
                      progress_color=T["P600"]).pack(side="right", padx=12, pady=10)

        # ── Save button ────────────────────────────────────────────────────
        ctk.CTkFrame(panel, fg_color=T["N200"], height=1,
                      corner_radius=0).pack(fill="x")
        ctk.CTkButton(panel, text="Save & Close", height=46,
                      corner_radius=R_PILL, font=(_SANS, 13, "bold"),
                      fg_color=T["P600"], hover_color=T["P700"],
                      command=self._save_settings).pack(
            fill="x", padx=16, pady=14)

    def _open_settings(self):
        """Slide the Settings panel into view."""
        if not self._settings_open:
            self._settings_open = True
            self._settings_panel.place(relx=1.0, rely=0.045,
                                       anchor="ne",
                                       relheight=0.955,
                                       width=440)
            self._settings_panel.lift()

    def _close_settings(self):
        """Hide the Settings panel."""
        self._settings_open = False
        self._settings_panel.place_forget()

    def _save_settings(self):
        """Persist settings, then redraw the grid if currency / std_id changed."""
        locale = self._locale_var.get()
        self._decimal_sep   = "," if locale == "German" else "."
        self._thousand_sep  = "." if locale == "German" else ","
        self._pdf_dir       = Path(
            self._folder_var.get().strip() or
            str(Path.home() / "Downloads" / "UR_Extracts")).expanduser()
        self._log_together  = self._log_together_var.get()
        self._log_dir       = (self._pdf_dir / "logs" if self._log_together else
                                Path(self._log_folder_var.get().strip() or
                                     str(self._log_dir)).expanduser())
        self._log_delete    = self._log_delete_var.get()
        self._currency_unit = self._currency_var.get()
        self._show_std_id   = self._std_id_var.get()
        _save_user_prefs({
            "pdf_dir":             str(self._pdf_dir),
            "log_dir":             str(self._log_dir),
            "log_together":        self._log_together,
            "log_delete_on_close": self._log_delete,
            "decimal_sep":         self._decimal_sep,
            "currency_unit":       self._currency_unit,
            "theme":               self._theme_name,
            "show_std_id":         self._show_std_id,
        })
        self._close_settings()
        co = self._active_company or {}
        if self._canvas_state == "overview" and co.get("overview_tables"):
            self._draw_financial_grid(self._active_inner_tab)

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_theme(self, name: str):
        """Switch Light / Dark appearance and restyle the grid."""
        self._theme_name = name
        ctk.set_appearance_mode(
            "light" if name.lower().startswith("l") else "dark")
        self._style_treeview()

    # ── Debug log ─────────────────────────────────────────────────────────────

    def _toggle_log_panel(self):
        """Show / hide the debug log drawer."""
        self._log_visible = not self._log_visible
        if self._log_hdr:
            if self._log_visible:
                self._log_hdr.grid()
                if self._log_frame:
                    self._log_frame.grid()
            else:
                self._log_hdr.grid_remove()
                if self._log_frame:
                    self._log_frame.grid_remove()

    def _clear_log(self):
        """Clear the debug log text."""
        if self._log_text:
            self._log_text.configure(state="normal")
            self._log_text.delete("1.0", "end")
            self._log_text.configure(state="disabled")

    def _append_log(self, line: str):
        """Append a line to the debug log (colour-coded by level)."""
        if not self._log_text:
            return
        lo  = line.lower()
        tag = ("err"  if any(w in lo for w in ("error", "failed", "exception", "traceback"))
               else "ok"   if any(w in lo for w in ("downloaded", "loaded", "success", "ok"))
               else "info")
        self._log_text.configure(state="normal")
        self._log_text.insert("end", line + "\n", tag)
        nlines = int(self._log_text.index("end-1c").split(".")[0])
        if nlines > 1000:
            self._log_text.delete("1.0", f"{nlines-1000}.0")
        self._log_text.configure(state="disabled")
        self._log_text.see("end")

    # ── Closing ───────────────────────────────────────────────────────────────

    def on_closing(self):
        # Flush any debounced library save synchronously so the last edit persists.
        """Flush a pending library save, stop the worker, and close the window."""
        if self._lib_save_after is not None:
            try:
                self.after_cancel(self._lib_save_after)
            except Exception:
                pass
            self._lib_save_after = None
        co = self._lib_pending_co or self._active_company
        if co and co.get("all_tables"):
            try:
                save_company_to_library(co)
            except Exception:
                pass
        self._worker.send("quit")
        self._worker.wait_done(timeout=4.0)
        _SESSION_LOG.close()
        self.destroy()


# ── Entry ─────────────────────────────────────────────────────────────────────

def main():
    """Construct the app, wire the close handler, and enter the Tk mainloop."""
    app = URExtractorApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as _startup_err:
        import traceback as _tb
        _detail = _tb.format_exc()
        try:
            import tkinter.messagebox as _mb2
            _mb2.showerror(
                "UR Financial Extractor — Startup Error",
                f"The application failed to start:\n\n{_startup_err}\n\n"
                f"Log: {_SESSION_LOG.log_path or 'unavailable'}",
            )
        except Exception:
            pass
        _SESSION_LOG.write_line(f"FATAL STARTUP ERROR:\n{_detail}")
        _SESSION_LOG.close()
        raise
