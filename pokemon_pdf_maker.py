"""
Pokemon Proxy PDF Maker
=======================
A simple desktop GUI that turns a Limitless decklist (.txt) into a print-ready
PDF of proxy cards. It wraps the silhouette-card-maker Pokemon plugin:

    1. Reads your decklist text file (Limitless export format)
    2. Downloads each card image from Limitless
    3. Lays the cards out on paper and saves a PDF

Built to be packaged into a single Windows .exe with PyInstaller.
"""

import os
import sys
import json
import queue
import shutil
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# ---------------------------------------------------------------------------
# Make the bundled repo importable, whether running from source or a frozen exe
# ---------------------------------------------------------------------------
def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        # PyInstaller extracts bundled data here
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _base_dir()
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Imports from the silhouette-card-maker project
from plugins.pokemon.deck_formats import DeckFormat, parse_deck  # noqa: E402
from plugins.pokemon.limitless import get_handle_card  # noqa: E402
from plugins.pokemon import limitless as _limitless  # noqa: E402
from utilities import ensure_directory, generate_pdf, Registration, FitMode  # noqa: E402
import filetype  # noqa: E402
from requests.exceptions import HTTPError  # noqa: E402


# ---------------------------------------------------------------------------
# Quality patch: prefer the high-resolution pokemontcg.io "_hires" images
# (~733x1024) over the low-resolution Limitless CDN "LG" images (~460x640).
#
# This lives here (rather than editing the upstream limitless.py) so the build
# stays reproducible against a fresh clone of silhouette-card-maker. We extend
# the set-id map with modern sets and reorder fetch_card to try the sharp CDN
# image first, falling back to Limitless exactly as before.
# ---------------------------------------------------------------------------
_MODERN_SET_MAP = {
    # HGSS / BW / XY / SM / SWSH / SV eras — Limitless codes == pokemontcg.io
    # ptcgoCode for these, used to build direct "_hires" CDN URLs.
    "HS": "hgss1", "UL": "hgss2", "UD": "hgss3", "TM": "hgss4", "CL": "col1",
    "BLW": "bw1", "EPO": "bw2", "NVI": "bw3", "NXD": "bw4", "DEX": "bw5",
    "DRX": "bw6", "DRV": "dv1", "BCR": "bw7", "PLS": "bw8", "PLF": "bw9",
    "PLB": "bw10", "LTR": "bw11", "BW": "bw1",
    "KSS": "xy0", "XY": "xy1", "FLF": "xy2", "FFI": "xy3", "PHF": "xy4",
    "PRC": "xy5", "DCR": "dc1", "ROS": "xy6", "AOR": "xy7", "BKT": "xy8",
    "BKP": "xy9", "GEN": "g1", "FCO": "xy10", "STS": "xy11", "EVO": "xy12",
    "SUM": "sm1", "GRI": "sm2", "BUS": "sm3", "SLG": "sm35", "CIN": "sm4",
    "UPR": "sm5", "FLI": "sm6", "CES": "sm7", "DRM": "sm75", "LOT": "sm8",
    "TEU": "sm9", "DET": "det1", "UNB": "sm10", "UNM": "sm11", "HIF": "sma",
    "CEC": "sm12",
    "SSH": "swsh1", "RCL": "swsh2", "DAA": "swsh3", "CPA": "swsh35",
    "VIV": "swsh4", "SHF": "swsh45sv", "BST": "swsh5", "CRE": "swsh6",
    "EVS": "swsh7", "CEL": "cel25c", "FST": "swsh8", "FUT20": "fut20",
    "BRS": "swsh9", "ASR": "swsh10", "PGO": "pgo", "LOR": "swsh11",
    "SIT": "swsh12", "CRZ": "swsh12pt5",
    "SVI": "sv1", "PAL": "sv2", "SVE": "sve", "OBF": "sv3", "MEW": "sv3pt5",
    "PAR": "sv4", "PAF": "sv4pt5", "TEF": "sv5", "TWM": "sv6", "SFA": "sv6pt5",
    "SCR": "sv7", "SSP": "sv8", "PRE": "sv8pt5", "JTG": "sv9", "DRI": "sv10",
    "BLK": "zsv10pt5", "WHT": "rsv10pt5",
    "MEG": "me1", "PFL": "me2", "ASC": "me2pt5", "POR": "me3", "CRI": "me4",
    "PBL": "me5",
}


def _fetch_card_hires(index, quantity, card_name, set_id, card_number, front_img_dir):
    """High-resolution replacement for limitless.fetch_card (hires CDN first)."""
    L = _limitless
    card_art = None

    # 1) High-res pokemontcg.io "_hires" CDN (precise: set + number)
    if set_id in L.LIMITLESS_TO_POKEMONTCG_SET_ID:
        try:
            pid = L.LIMITLESS_TO_POKEMONTCG_SET_ID[set_id]
            url = L.POKEMONTCG_IMAGE_URL_TEMPLATE.format(set_id=pid, card_no=card_number)
            card_art = L.request_pokemontcg(url).content
        except HTTPError:
            pass

    # 2) Limitless TCG CDN (lower-res fallback)
    if card_art is None and set_id not in L._failed_tcg_sets:
        try:
            url = L.LIMITLESS_TCG_URL_TEMPLATE.format(set_id=set_id, card_no=str(card_number).zfill(3))
            card_art = L.request_limitless(url).content
        except HTTPError:
            L._failed_tcg_sets.add(set_id)

    # 3) Pokemon Pocket format
    if card_art is None and set_id not in L._failed_pocket_sets:
        try:
            url = L.LIMITLESS_POCKET_URL_TEMPLATE.format(set_id=set_id, card_no=str(card_number).zfill(3))
            card_art = L.request_limitless(url).content
        except HTTPError:
            L._failed_pocket_sets.add(set_id)

    # 4) pokemontcg.io search API (by name + number)
    if card_art is None:
        try:
            card_art = L.fetch_card_from_pokemontcg(card_name, card_number)
        except Exception as e:
            raise Exception(f'Failed to fetch card "{card_name}" (set: {set_id}, number: {card_number}): {e}')

    file_ext = filetype.guess(card_art).extension
    for counter in range(quantity):
        image_path = os.path.join(front_img_dir, f'{index}{card_name}{counter + 1}.{file_ext}')
        with open(image_path, 'wb') as f:
            f.write(card_art)


def _install_hires_patch():
    _limitless.LIMITLESS_TO_POKEMONTCG_SET_ID.update(_MODERN_SET_MAP)
    _limitless.fetch_card = _fetch_card_hires  # get_handle_card looks this up at call time


_install_hires_patch()


APP_TITLE = "Pokemon Proxy PDF Maker"

# House style: GitHub-dark inspired palette
CLR = {
    "bg":       "#0d1117",  # page background
    "panel":    "#161b22",  # card / panel background
    "border":   "#30363d",
    "text":     "#c9d1d9",
    "muted":    "#8b949e",
    "heading":  "#f0f6fc",
    "input_bg": "#0d1117",
    "accent":   "#238636",  # primary green
    "accent_hi": "#2ea043",
    "accent_tx": "#ffffff",
    "log_bg":   "#010409",
    "log_fg":   "#adbac7",
    "link":     "#58a6ff",
}


def default_output_dir() -> str:
    """Pick a sensible, writable default output folder (Desktop, else home)."""
    home = os.path.expanduser("~")
    desktop = os.path.join(home, "Desktop")
    base = desktop if os.path.isdir(desktop) else home
    out = os.path.join(base, "Pokemon Proxies")
    return out


CUSTOM_CARD = "custom"          # value shown in the UI
_CUSTOM_INTERNAL = "__custom__"  # internal card-size key injected into the layout


def _best_orientation(w_mm: float, h_mm: float, paper: str, borderless: bool):
    """Return (orientation, cards_per_page) that fits the most custom-size cards."""
    import utilities as U
    import page_manager as PM
    import size_convert as SC
    from enums import Orientation

    cfg = U.load_layout_config()
    paper = U.resolve_paper_size_alias(cfg, paper)
    pdef = cfg.paper_sizes[paper]
    reg = cfg.defaults.registration
    inset = reg.borderless.inset if borderless else reg.default.inset
    length = f"{SC.size_to_mm(reg.default.length) + PM.REG_PADDING_MM}mm"

    best = ("portrait", 0)
    for ori in (Orientation.PORTRAIT, Orientation.LANDSCAPE):
        try:
            c = PM.generate_layout(orientation=ori, card_width=f"{w_mm}mm",
                                   card_height=f"{h_mm}mm", paper_width=pdef.width,
                                   paper_height=pdef.height, inset=inset,
                                   length=length, ppi=cfg.ppi)
            n = len(c.x_pos) * len(c.y_pos)
        except Exception:
            n = 0
        if n > best[1]:
            best = (ori.value, n)
    return best


def make_pdf(deck: str, back: str, outdir: str, paper: str, card: str,
             borderless: bool = False, custom_size=None, log=print) -> str | None:
    """Core job shared by the GUI and CLI: fetch card images, build the PDF.

    `custom_size` is an optional (width_mm, height_mm) tuple, used when
    `card == "custom"`.

    Returns the output PDF path on success, or None on failure.
    """
    deck_name = os.path.splitext(os.path.basename(deck))[0]
    work = os.path.join(outdir, "_work_" + deck_name)
    front_dir = os.path.join(work, "front")
    back_dir = os.path.join(work, "back")
    ds_dir = os.path.join(work, "double_sided")

    # Fresh working directories each run
    if os.path.isdir(front_dir):
        shutil.rmtree(front_dir, ignore_errors=True)
    ensure_directory(front_dir)
    ensure_directory(back_dir)
    ensure_directory(ds_dir)
    ensure_directory(outdir)

    # Optional user-supplied card back
    for f in os.listdir(back_dir):
        try:
            os.remove(os.path.join(back_dir, f))
        except OSError:
            pass
    if back and os.path.isfile(back):
        shutil.copy2(back, os.path.join(back_dir, os.path.basename(back)))

    # 1) Fetch card images from Limitless
    log(">>> Downloading card images from Limitless…\n")
    with open(deck, "r", encoding="utf-8") as fh:
        deck_text = fh.read()
    parse_deck(deck_text, DeckFormat.LIMITLESS, get_handle_card(front_dir))

    n = len([f for f in os.listdir(front_dir) if os.path.isfile(os.path.join(front_dir, f))])
    if n == 0:
        log("\nNo card images were downloaded. Check the decklist format.\n")
        return None
    log(f"\n>>> Downloaded {n} card images.\n>>> Building PDF…\n")

    # 2a) Custom card size: inject a temporary layout the engine can auto-fit.
    card_size = card
    prev_env = os.environ.get("SCM_EXTRA_LAYOUTS")
    if card == CUSTOM_CARD:
        if not custom_size:
            log("\nCustom card size selected but no dimensions were given.\n")
            return None
        w_mm, h_mm = custom_size
        ori, per_page = _best_orientation(w_mm, h_mm, paper, borderless)
        if per_page == 0:
            log(f"\nThose custom dimensions ({w_mm}×{h_mm} mm) don't fit on {paper}.\n")
            return None
        variant_def = {"orientation": ori, "version": 1, "registration": {"length": "8mm"}}
        extra = {
            "card_sizes": {_CUSTOM_INTERNAL: {"width": f"{w_mm}mm", "height": f"{h_mm}mm"}},
            "layouts": {paper: {_CUSTOM_INTERNAL: {"default": variant_def,
                                                   "borderless": variant_def}}},
        }
        extra_path = os.path.join(work, "extra_layout.json")
        with open(extra_path, "w") as ef:
            json.dump(extra, ef)
        os.environ["SCM_EXTRA_LAYOUTS"] = extra_path
        card_size = _CUSTOM_INTERNAL
        log(f">>> Custom card size {w_mm}×{h_mm} mm on {paper}: "
            f"{per_page} cards/page ({ori}).\n")

    # 2b) Build the PDF
    output_pdf = os.path.join(outdir, deck_name + ".pdf")
    try:
        generate_pdf(
            front_dir_path=front_dir,
            back_dir_path=back_dir,
            ds_dir_path=ds_dir,
            output_path=output_pdf,
            output_images=False,
            card_size=card_size,
            paper_size=paper,
            registration=Registration.THREE.value,
            only_fronts=False,
            fit=FitMode.STRETCH.value,
            fit_backs=None,
            crop_string=None,
            crop_backs_string=None,
            extend_edges=None,
            extend_edges_backs=None,
            extend_corners=None,
            extend_corners_backs=None,
            extend_bleed=None,
            extend_bleed_backs=None,
            ppi=300,
            quality=100,
            skip_indices=[],
            load_offset=False,
            label=None,
            borderless=borderless,
        )
    finally:
        # Restore the environment so a custom run never leaks into the next one
        if prev_env is None:
            os.environ.pop("SCM_EXTRA_LAYOUTS", None)
        else:
            os.environ["SCM_EXTRA_LAYOUTS"] = prev_env

    log(f"\n>>> Done! PDF saved to:\n{output_pdf}\n")
    return output_pdf


class StdoutRedirector:
    """Send print()/stdout writes into a thread-safe queue for the log box."""

    def __init__(self, q: "queue.Queue[str]"):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(text)

    def flush(self):
        pass


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.worker: threading.Thread | None = None

        root.title(APP_TITLE)
        root.geometry("780x720")
        root.minsize(700, 660)

        self.deck_path = tk.StringVar()
        self.back_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=default_output_dir())
        self.paper_size = tk.StringVar(value="letter")
        self.card_size = tk.StringVar(value="standard")
        self.custom_w = tk.StringVar(value="63")
        self.custom_h = tk.StringVar(value="88")
        self.borderless = tk.BooleanVar(value=False)

        self._apply_theme()
        self._build_ui()
        self._poll_log()

    # --------------------------------------------------------------- theming
    def _apply_theme(self):
        """Apply the GitHub-dark house style to all ttk widgets."""
        self.root.configure(bg=CLR["bg"])
        st = ttk.Style()
        st.theme_use("clam")  # only fully-restylable built-in theme

        st.configure(".", background=CLR["bg"], foreground=CLR["text"],
                     fieldbackground=CLR["input_bg"], bordercolor=CLR["border"],
                     lightcolor=CLR["border"], darkcolor=CLR["border"],
                     font=("Segoe UI", 10))
        st.configure("TFrame", background=CLR["bg"])
        st.configure("Card.TFrame", background=CLR["panel"], relief="flat")
        st.configure("TLabel", background=CLR["bg"], foreground=CLR["text"])
        st.configure("Card.TLabel", background=CLR["panel"], foreground=CLR["text"])
        st.configure("Muted.TLabel", background=CLR["bg"], foreground=CLR["muted"])
        st.configure("MutedCard.TLabel", background=CLR["panel"], foreground=CLR["muted"])
        st.configure("Heading.TLabel", background=CLR["bg"], foreground=CLR["heading"],
                     font=("Segoe UI Semibold", 18))

        # Entries
        st.configure("TEntry", fieldbackground=CLR["input_bg"], foreground=CLR["text"],
                     insertcolor=CLR["text"], bordercolor=CLR["border"],
                     lightcolor=CLR["border"], darkcolor=CLR["border"], padding=5)
        st.map("TEntry", bordercolor=[("focus", CLR["accent_hi"])])

        # Secondary (Browse) buttons
        st.configure("TButton", background=CLR["panel"], foreground=CLR["text"],
                     bordercolor=CLR["border"], focuscolor=CLR["panel"], padding=(10, 5))
        st.map("TButton",
               background=[("active", "#21262d"), ("pressed", "#21262d")],
               bordercolor=[("active", CLR["muted"])])

        # Primary (Make PDF) button
        st.configure("Accent.TButton", background=CLR["accent"], foreground=CLR["accent_tx"],
                     bordercolor=CLR["accent"], focuscolor=CLR["accent"],
                     font=("Segoe UI Semibold", 11), padding=(16, 9))
        st.map("Accent.TButton",
               background=[("active", CLR["accent_hi"]), ("pressed", CLR["accent_hi"]),
                           ("disabled", "#20301f")],
               foreground=[("disabled", "#7d8590")])

        # Comboboxes
        st.configure("TCombobox", fieldbackground=CLR["input_bg"], background=CLR["panel"],
                     foreground=CLR["text"], arrowcolor=CLR["text"],
                     bordercolor=CLR["border"], padding=4)
        st.map("TCombobox", fieldbackground=[("readonly", CLR["input_bg"])],
               foreground=[("readonly", CLR["text"])])
        self.root.option_add("*TCombobox*Listbox.background", CLR["panel"])
        self.root.option_add("*TCombobox*Listbox.foreground", CLR["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", CLR["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", CLR["accent_tx"])

        # Checkbutton
        st.configure("Card.TCheckbutton", background=CLR["panel"], foreground=CLR["text"],
                     focuscolor=CLR["panel"], indicatorcolor=CLR["input_bg"],
                     indicatorbackground=CLR["input_bg"])
        st.map("Card.TCheckbutton",
               indicatorcolor=[("selected", CLR["accent"])],
               background=[("active", CLR["panel"])])

        # Progress + scrollbar
        st.configure("TProgressbar", background=CLR["accent"], troughcolor=CLR["panel"],
                     bordercolor=CLR["panel"], lightcolor=CLR["accent"], darkcolor=CLR["accent"])
        st.configure("Vertical.TScrollbar", background=CLR["panel"], troughcolor=CLR["bg"],
                     bordercolor=CLR["bg"], arrowcolor=CLR["muted"])

    # ------------------------------------------------------------------ UI
    def _card(self, parent):
        """A GitHub-style bordered panel."""
        outer = tk.Frame(parent, bg=CLR["border"])            # 1px border
        inner = ttk.Frame(outer, style="Card.TFrame", padding=14)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return outer, inner

    def _row(self, parent, r, label, var, browse_cmd):
        ttk.Label(parent, text=label, style="Card.TLabel").grid(
            row=r, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(parent, textvariable=var).grid(row=r, column=1, sticky="ew", pady=6)
        ttk.Button(parent, text="Browse…", command=browse_cmd).grid(
            row=r, column=2, padx=(8, 0), pady=6)

    def _build_ui(self):
        # Header
        head = ttk.Frame(self.root)
        head.pack(fill="x", padx=16, pady=(16, 4))
        ttk.Label(head, text="🃏  Pokémon Proxy PDF Maker", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(head, style="Muted.TLabel",
                  text="Turn a Limitless decklist (.txt) into a high-resolution, print-ready PDF."
                  ).pack(anchor="w", pady=(2, 0))

        # Inputs card
        card_o, card = self._card(self.root)
        card_o.pack(fill="x", padx=16, pady=8)
        card.columnconfigure(1, weight=1)
        self._row(card, 0, "Decklist (.txt)", self.deck_path, self._pick_deck)
        self._row(card, 1, "Card back (optional)", self.back_path, self._pick_back)
        self._row(card, 2, "Output folder", self.output_dir, self._pick_output)

        # Options card
        opt_o, opt = self._card(self.root)
        opt_o.pack(fill="x", padx=16, pady=(0, 8))
        ttk.Label(opt, text="Paper size", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Combobox(opt, textvariable=self.paper_size, values=["letter", "a4"],
                     width=9, state="readonly").grid(row=0, column=1, sticky="w", padx=(0, 20))
        ttk.Label(opt, text="Card size", style="Card.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6))
        card_cb = ttk.Combobox(opt, textvariable=self.card_size,
                     values=["standard", "japanese", "poker", "bridge", CUSTOM_CARD],
                     width=12, state="readonly")
        card_cb.grid(row=0, column=3, sticky="w")
        card_cb.bind("<<ComboboxSelected>>", lambda e: self._sync_custom_state())

        # Custom size row (enabled only when card size == "custom")
        self.custom_row = ttk.Frame(opt, style="Card.TFrame")
        self.custom_row.grid(row=1, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Label(self.custom_row, text="Custom size", style="Card.TLabel").pack(side="left", padx=(0, 8))
        self.custom_w_entry = ttk.Entry(self.custom_row, textvariable=self.custom_w, width=6)
        self.custom_w_entry.pack(side="left")
        ttk.Label(self.custom_row, text="×", style="Card.TLabel").pack(side="left", padx=6)
        self.custom_h_entry = ttk.Entry(self.custom_row, textvariable=self.custom_h, width=6)
        self.custom_h_entry.pack(side="left")
        ttk.Label(self.custom_row, text="mm  (width × height)", style="MutedCard.TLabel").pack(side="left", padx=(8, 0))

        ttk.Checkbutton(opt, text="Borderless (fit more cards per page)",
                        variable=self.borderless, style="Card.TCheckbutton"
                        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(12, 0))
        ttk.Label(opt, style="MutedCard.TLabel", wraplength=680, justify="left",
                  text="Borderless uses a denser layout (e.g. 3×3 instead of 4×2 on Letter). "
                       "For cutting you'll need the matching borderless templates from the "
                       "silhouette-card-maker project."
                  ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 0))
        self._sync_custom_state()

    def _sync_custom_state(self):
        """Enable the custom width/height fields only when 'custom' is chosen."""
        state = "normal" if self.card_size.get() == CUSTOM_CARD else "disabled"
        self.custom_w_entry.configure(state=state)
        self.custom_h_entry.configure(state=state)

        # Action button
        self.run_btn = ttk.Button(self.root, text="Make PDF", style="Accent.TButton",
                                  command=self._on_run)
        self.run_btn.pack(pady=(6, 6))

        # Progress bar
        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill="x", padx=16, pady=(0, 8))

        # Log box
        ttk.Label(self.root, text="Progress", style="Muted.TLabel").pack(anchor="w", padx=16)
        log_o = tk.Frame(self.root, bg=CLR["border"])
        log_o.pack(fill="both", expand=True, padx=16, pady=(2, 16))
        log_frame = tk.Frame(log_o, bg=CLR["log_bg"])
        log_frame.pack(fill="both", expand=True, padx=1, pady=1)
        self.log = tk.Text(log_frame, height=13, wrap="word", state="disabled",
                           background=CLR["log_bg"], foreground=CLR["log_fg"],
                           insertbackground=CLR["log_fg"], relief="flat", borderwidth=0,
                           padx=8, pady=6, font=("Consolas", 9))
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    # -------------------------------------------------------------- pickers
    def _pick_deck(self):
        p = filedialog.askopenfilename(
            title="Select decklist text file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if p:
            self.deck_path.set(p)

    def _pick_back(self):
        p = filedialog.askopenfilename(
            title="Select card back image (optional)",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")],
        )
        if p:
            self.back_path.set(p)

    def _pick_output(self):
        p = filedialog.askdirectory(title="Select output folder")
        if p:
            self.output_dir.set(p)

    # -------------------------------------------------------------- logging
    def _log_write(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                self._log_write(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log)

    # -------------------------------------------------------------- run flow
    def _on_run(self):
        deck = self.deck_path.get().strip()
        if not deck or not os.path.isfile(deck):
            messagebox.showerror(APP_TITLE, "Please select a valid decklist .txt file.")
            return

        outdir = self.output_dir.get().strip() or default_output_dir()
        back = self.back_path.get().strip()

        custom_size = None
        if self.card_size.get() == CUSTOM_CARD:
            try:
                custom_size = (float(self.custom_w.get()), float(self.custom_h.get()))
                if custom_size[0] <= 0 or custom_size[1] <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(APP_TITLE,
                                     "Enter a valid custom size in mm (e.g. 63 × 88).")
                return

        self.run_btn.configure(state="disabled")
        self.progress.start(12)
        self._log_write("\n" + "=" * 60 + "\nStarting…\n")

        self.worker = threading.Thread(
            target=self._run_job,
            args=(deck, back, outdir, self.paper_size.get(), self.card_size.get(),
                  self.borderless.get(), custom_size),
            daemon=True,
        )
        self.worker.start()

    def _run_job(self, deck: str, back: str, outdir: str, paper: str, card: str,
                 borderless: bool, custom_size):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = StdoutRedirector(self.log_queue)
        result_pdf = None
        try:
            result_pdf = make_pdf(deck, back, outdir, paper, card,
                                  borderless=borderless, custom_size=custom_size,
                                  log=print)
        except Exception:
            print("\n!!! Something went wrong:\n")
            print(traceback.format_exc())
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            self.root.after(0, lambda: self._job_done(result_pdf))

    def _job_done(self, result_pdf):
        self.progress.stop()
        self.run_btn.configure(state="normal")
        if result_pdf and os.path.isfile(result_pdf):
            if messagebox.askyesno(APP_TITLE, "PDF created!\n\nOpen it now?"):
                try:
                    os.startfile(result_pdf)  # type: ignore[attr-defined]
                except Exception:
                    messagebox.showinfo(APP_TITLE, f"Saved to:\n{result_pdf}")
        else:
            messagebox.showwarning(APP_TITLE, "Finished, but no PDF was produced. See the log.")


def run_cli(argv) -> int:
    """Headless command-line mode. Usage:
    PokemonPDFMaker.exe --cli <deck.txt> [--out DIR] [--paper letter|a4]
                        [--card standard] [--back IMAGE]
    """
    import argparse
    p = argparse.ArgumentParser(prog="PokemonPDFMaker", description="Make a Pokemon proxy PDF from a Limitless decklist.")
    p.add_argument("deck", help="Path to the decklist .txt file (Limitless format)")
    p.add_argument("--out", default=default_output_dir(), help="Output folder")
    p.add_argument("--paper", default="letter", help="Paper size (e.g. letter, a4)")
    p.add_argument("--card", default="standard",
                   help="Card size name (default: standard), or 'custom' with --card-mm.")
    p.add_argument("--card-mm", default="",
                   help="Custom card size in mm as WxH, e.g. 60x85. Implies --card custom.")
    p.add_argument("--back", default="", help="Optional card back image")
    p.add_argument("--borderless", action="store_true",
                   help="Denser layout that fits more cards per page (needs borderless cutting templates).")
    args = p.parse_args(argv)

    if not os.path.isfile(args.deck):
        print(f"Decklist not found: {args.deck}")
        return 2

    card = args.card
    custom_size = None
    if args.card_mm:
        try:
            w, h = (float(x) for x in args.card_mm.lower().replace("mm", "").split("x"))
            custom_size = (w, h)
            card = CUSTOM_CARD
        except Exception:
            print(f"Invalid --card-mm value '{args.card_mm}'. Use WxH, e.g. 60x85.")
            return 2

    try:
        pdf = make_pdf(args.deck, args.back, args.out, args.paper, card,
                       borderless=args.borderless, custom_size=custom_size, log=print)
    except Exception:
        print(traceback.format_exc())
        return 1
    return 0 if pdf else 1


def main():
    # Headless CLI: `--cli` flag, or first arg is an existing .txt file
    argv = sys.argv[1:]
    if argv and (argv[0] == "--cli" or (argv[0].lower().endswith(".txt") and os.path.isfile(argv[0]))):
        if argv and argv[0] == "--cli":
            argv = argv[1:]
        sys.exit(run_cli(argv))

    root = tk.Tk()
    App(root)  # applies the dark house-style theme internally
    root.mainloop()


if __name__ == "__main__":
    main()
