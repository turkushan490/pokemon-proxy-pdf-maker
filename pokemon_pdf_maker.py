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
from utilities import ensure_directory, generate_pdf, Registration, FitMode  # noqa: E402


APP_TITLE = "Pokemon Proxy PDF Maker"


def default_output_dir() -> str:
    """Pick a sensible, writable default output folder (Desktop, else home)."""
    home = os.path.expanduser("~")
    desktop = os.path.join(home, "Desktop")
    base = desktop if os.path.isdir(desktop) else home
    out = os.path.join(base, "Pokemon Proxies")
    return out


def make_pdf(deck: str, back: str, outdir: str, paper: str, card: str, log=print) -> str | None:
    """Core job shared by the GUI and CLI: fetch card images, build the PDF.

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

    # 2) Build the PDF
    output_pdf = os.path.join(outdir, deck_name + ".pdf")
    generate_pdf(
        front_dir_path=front_dir,
        back_dir_path=back_dir,
        ds_dir_path=ds_dir,
        output_path=output_pdf,
        output_images=False,
        card_size=card,
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
    )
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
        root.geometry("760x620")
        root.minsize(680, 560)

        self.deck_path = tk.StringVar()
        self.back_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=default_output_dir())
        self.paper_size = tk.StringVar(value="letter")
        self.card_size = tk.StringVar(value="standard")

        self._build_ui()
        self._poll_log()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        header = ttk.Label(
            self.root,
            text="Pokemon Proxy PDF Maker",
            font=("Segoe UI", 16, "bold"),
        )
        header.pack(anchor="w", padx=12, pady=(12, 0))
        ttk.Label(
            self.root,
            text="Paste a Limitless decklist into a .txt file, pick it below, and make a PDF.",
            foreground="#555",
        ).pack(anchor="w", padx=12, pady=(0, 8))

        form = ttk.Frame(self.root)
        form.pack(fill="x", padx=8)
        form.columnconfigure(1, weight=1)

        # Decklist file
        ttk.Label(form, text="Decklist (.txt):").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(form, textvariable=self.deck_path).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(form, text="Browse…", command=self._pick_deck).grid(row=0, column=2, **pad)

        # Card back (optional)
        ttk.Label(form, text="Card back (optional):").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(form, textvariable=self.back_path).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(form, text="Browse…", command=self._pick_back).grid(row=1, column=2, **pad)

        # Output folder
        ttk.Label(form, text="Output folder:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(form, textvariable=self.output_dir).grid(row=2, column=1, sticky="ew", **pad)
        ttk.Button(form, text="Browse…", command=self._pick_output).grid(row=2, column=2, **pad)

        # Options row
        opts = ttk.Frame(form)
        opts.grid(row=3, column=0, columnspan=3, sticky="w", padx=10, pady=(2, 4))
        ttk.Label(opts, text="Paper size:").pack(side="left")
        ttk.Combobox(
            opts, textvariable=self.paper_size, values=["letter", "a4"],
            width=10, state="readonly",
        ).pack(side="left", padx=(4, 16))
        ttk.Label(opts, text="Card size:").pack(side="left")
        ttk.Combobox(
            opts, textvariable=self.card_size, values=["standard", "japanese", "poker", "bridge"],
            width=12, state="readonly",
        ).pack(side="left", padx=(4, 0))

        # Action button
        self.run_btn = ttk.Button(self.root, text="Make PDF", command=self._on_run)
        self.run_btn.pack(pady=(4, 4))

        # Progress bar
        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill="x", padx=12, pady=(0, 6))

        # Log box
        ttk.Label(self.root, text="Progress:").pack(anchor="w", padx=12)
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log = tk.Text(log_frame, height=14, wrap="word", state="disabled",
                           background="#1e1e1e", foreground="#d4d4d4",
                           insertbackground="#d4d4d4", font=("Consolas", 9))
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

        self.run_btn.configure(state="disabled")
        self.progress.start(12)
        self._log_write("\n" + "=" * 60 + "\nStarting…\n")

        self.worker = threading.Thread(
            target=self._run_job,
            args=(deck, back, outdir, self.paper_size.get(), self.card_size.get()),
            daemon=True,
        )
        self.worker.start()

    def _run_job(self, deck: str, back: str, outdir: str, paper: str, card: str):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = StdoutRedirector(self.log_queue)
        result_pdf = None
        try:
            result_pdf = make_pdf(deck, back, outdir, paper, card, log=print)
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
    p.add_argument("--card", default="standard", help="Card size (default: standard)")
    p.add_argument("--back", default="", help="Optional card back image")
    args = p.parse_args(argv)

    if not os.path.isfile(args.deck):
        print(f"Decklist not found: {args.deck}")
        return 2
    try:
        pdf = make_pdf(args.deck, args.back, args.out, args.paper, args.card, log=print)
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
    try:
        # Nicer default theme on Windows
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
