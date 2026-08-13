# 🃏 Pokémon Proxy PDF Maker

A dead-simple **Windows app** that turns a [Limitless](https://limitlesstcg.com/)
Pokémon decklist (a plain `.txt` file) into a **print-ready PDF of proxy cards**.

Pick your decklist → click one button → get a PDF with all the real card art,
laid out on **Letter or A4** paper, ready to print and cut.

> This is a friendly one-click wrapper + Windows `.exe` around the excellent
> **[silhouette-card-maker](https://github.com/Alan-Cha/silhouette-card-maker)**
> project by **[Alan Cha](https://github.com/Alan-Cha)**. All the heavy lifting
> (fetching card art from Limitless and laying out the PDF) is his work — this
> repo just wraps its **[Pokémon plugin](https://alan-cha.github.io/silhouette-card-maker/plugins/pokemon/)**
> in a GUI and packages it as a standalone executable so non-technical users
> don't need Python or the command line.

---

## ✨ Features

- 🖱️ **One-click GUI** — no Python, no terminal, no setup (dark GitHub-style theme)
- 🔍 **High-resolution card art** — pulls the sharp `~733×1024` "hires" images from
  pokemontcg.io first (≈2.5× the pixels of the old `460×640` Limitless art),
  with Limitless as an automatic fallback
- 🎚️ **Image-quality selector** — `highest` (hi-res, the default) or `standard`
  (smaller/faster Limitless art)
- 📄 **Letter *or* A4** paper size
- 🃏 **19 card sizes** — standard, japanese, poker, bridge, **mini, micro,
  american_mini, euro_mini**, jumbo, tarot, and more (list comes straight from
  the engine, so it always matches what actually prints)
- 📐 **Custom card size** — type any width × height in mm; the layout auto-fits
- 🧩 **Borderless mode** — denser layout that fits more cards per page
- 🖼️ Optional custom **card back** image
- 📂 Saves the PDF wherever you want (default: `Desktop\Pokemon Proxies\`)
- ⌨️ Hidden **command-line mode** for power users

---

## 🚀 Download & use (easiest)

1. Grab **`Pokemon PDF Maker.exe`** from the
   [**Releases**](../../releases/latest) page.
2. Double-click it.
3. **Browse…** to your decklist `.txt` (see [format](#-decklist-format) below).
4. *(Optional)* pick a card-back image and an output folder.
5. Choose **Paper size: Letter or A4**, and optionally tick **Borderless**.
6. Click **Make PDF**. It downloads the cards and builds the PDF, then offers
   to open it.

> ⚠️ Windows SmartScreen may warn because the `.exe` is unsigned →
> **More info → Run anyway**. Needs an internet connection.

---

## 📝 Decklist format

Export your list from **Limitless**, or write it yourself. Each card line is:

```
<quantity> <name> <set> <number>
```

Header lines like `Pokémon: 13` are ignored automatically. Example
([sample_deck.txt](sample_deck.txt)):

```
Pokémon: 6
3 Charcadet SSP 32
1 Charcadet PAR 26
3 Ceruledge ex SSP 36
2 Solrock MEG 75
2 Lunatone MEG 74
1 Squawkabilly ex PAL 169

Trainer: 8
3 Carmine TWM 145
3 Boss's Orders MEG 114
2 Professor's Research JTG 155
4 Ultra Ball MEG 131
4 Nest Ball SVI 181

Energy: 1
6 Basic Fire Energy SVE 10
```

---

## 🖥️ Command-line mode (optional)

```bat
"Pokemon PDF Maker.exe" --cli deck.txt --out "C:\folder" --paper a4 --card-mm 60x85 --borderless
```

Options: `--out FOLDER`  `--paper letter|a4`  `--card standard`  `--card-mm 60x85`  `--image-quality highest|standard`  `--back image.png`  `--borderless`

> **Custom size:** in the GUI, choose **Card size → custom** and type the width ×
> height in mm. On the command line use `--card-mm WxH` (e.g. `--card-mm 60x85`).
> The app picks the orientation that fits the most cards per page.

---

## 🔧 Build it yourself

You need **Python 3.11+** and **git** on your PATH. Then just run:

```bat
build_windows.bat
```

That script will:
1. Clone [silhouette-card-maker](https://github.com/Alan-Cha/silhouette-card-maker)
2. Drop [`pokemon_pdf_maker.py`](pokemon_pdf_maker.py) into it
3. Create a venv and install [dependencies](requirements.txt)
4. Package it into `dist\Pokemon PDF Maker.exe` with PyInstaller

*(The upstream project is intentionally **not** committed here — the build
script fetches it fresh so all credit and updates stay with the original.)*

---

## 🙏 Credits & links

| | |
|---|---|
| **Engine** | [silhouette-card-maker](https://github.com/Alan-Cha/silhouette-card-maker) by [Alan Cha](https://github.com/Alan-Cha) |
| **Pokémon plugin docs** | https://alan-cha.github.io/silhouette-card-maker/plugins/pokemon/ |
| **Card images** | [Limitless TCG](https://limitlesstcg.com/) |

## 📜 License

MIT — see [LICENSE](LICENSE). The bundled silhouette-card-maker code is also
MIT (© 2025 Alan Cha) and its license is included there.
