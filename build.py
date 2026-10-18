#!/usr/bin/env python3
"""Build the Elektra dictionary PDFs from the word files in ord/.

    python build.py              validate + build build/ordbok.pdf (and the print versions)
    python build.py --check      validate only (no LaTeX needed)
    python build.py --tex-only   write build/*.tex without running LaTeX (CI compiles it)

Every word is its own TOML file, ord/<id>.toml. The id (the file name) is what
[[vist tekst|id]] links and ordbok.pdf#id point to. Entries are sorted Norwegian-style
(0-9/symbols, A-Z, Æ, Ø, Å) and grouped under letter headings automatically. Entries
with an empty definition stay in ord/ but are left out of the PDF; links pointing to
them render as plain text.

Needs Python 3.11+ (tomllib) and nothing else; latexmk for the PDFs.
"""
import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import tomllib
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORDS = ROOT / "ord"
TEMPLATE = ROOT / "template"
ASSETS = ROOT / "assets"

# Where the finished PDF is read (QR code on the back of the printed booklet), and
# where people suggest new words (the "Mangler et ord?" link).
NETTSIDE = "https://elektra.io/ordbok"
FORSLAG = NETTSIDE + "/forslag"

FIELDS = ("ord", "nynorsk", "stikkord", "definisjon")
# digital PDF, A5 print pages, A4 booklet of the A5 pages (keep in sync with the CI workflows)
ROOT_FILES = ("ordbok.tex", "ordbok-a5.tex", "ordbok-utskrift.tex")
PDFS = ("ordbok.pdf", "ordbok-utskrift.pdf")  # the ones that get published
NO_LETTER = "Ikke bokstav"
MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
          "august", "september", "oktober", "november", "desember"]

# [[text]] / [[text|target]], *italic*, "quote"
TOKEN = re.compile(r'\[\[([^\[\]|]+?)(?:\|([^\[\]]+?))?\]\]|\*([^*\n]+?)\*|"([^"\n]+?)"')
ID_OK = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class OrdbokError(Exception):
    pass


# ---------------------------------------------------------------- sorting

_NORDIC = {"æ": "{", "ä": "{", "ø": "|", "ö": "|", "å": "}"}  # sort after z


def _fold(ch):
    ch = ch.lower()
    if ch in _NORDIC:
        return _NORDIC[ch]
    return unicodedata.normalize("NFD", ch)[0]


def sort_key(word):
    folded = "".join(_fold(c) for c in word.strip())
    return (0 if section_of(word) == NO_LETTER else 1, folded, word)


def section_of(word):
    first = _fold(word.strip()[:1] or "#")
    if first in "{|}":
        return {"{": "Æ", "|": "Ø", "}": "Å"}[first]
    if "a" <= first <= "z":
        return first.upper()
    return NO_LETTER


def slug(word):
    """File name (id) for a word: "Alt var bedre før" -> "alt-var-bedre-for"."""
    s = word.lower().replace("æ", "ae").replace("ø", "o").replace("å", "a")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "ord"


# ---------------------------------------------------------------- loading

def _clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize(raw, where):
    unknown = set(raw) - set(FIELDS)
    if unknown:
        raise OrdbokError(f"{where}: ukjente felt {sorted(unknown)} (lovlige: {', '.join(FIELDS)})")
    e = {}
    for key in FIELDS:
        value = raw.get(key, "")
        if not isinstance(value, str):
            raise OrdbokError(f"{where}: {key} må være tekst i anførselstegn, fikk {value!r}")
        e[key] = _clean(value)
    if not e["ord"]:
        raise OrdbokError(f"{where}: mangler 'ord'")
    return e


def read_entry(path):
    path = Path(path)
    where = f"{path.parent.name}/{path.name}"
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise OrdbokError(f"{where}: ikke gyldig TOML ({exc})")
    e = normalize(raw, where)
    e["id"], e["fil"] = path.stem, where
    if not ID_OK.match(e["id"]):
        raise OrdbokError(f"{where}: ugyldig filnavn – bruk bare a–z, 0–9 og bindestrek, "
                          f"f.eks. {slug(e['ord'])}.toml")
    return e


def load(folder=WORDS):
    folder = Path(folder)
    if not folder.is_dir():
        raise OrdbokError(f"fant ikke mappa {folder.name}/")
    entries, errors = [], []
    for path in sorted(folder.iterdir()):
        if path.name.startswith("."):
            continue
        if path.suffix != ".toml" or not path.is_file():
            errors.append(f"{folder.name}/{path.name}: bare ord-filer (.toml) hører hjemme i {folder.name}/")
            continue
        try:
            entries.append(read_entry(path))
        except OrdbokError as exc:
            errors.append(str(exc))
    seen = {}
    for e in entries:
        key = e["ord"].lower()
        if key in seen:
            errors.append(f"{e['fil']}: ordet {e['ord']!r} finnes allerede i {seen[key]} – slå dem sammen")
        seen.setdefault(key, e["fil"])
    # Render every definition once so broken links are caught here, not by LaTeX.
    if not errors:
        resolve = resolver(entries)
        for e in entries:
            render_text(e["definisjon"], resolve, e["fil"], errors)
    if errors:
        raise OrdbokError("\n".join(errors))
    return entries


def resolver(entries):
    by_id = {e["id"]: e for e in entries}
    by_word = {e["ord"].lower(): e for e in entries}
    return lambda target: by_id.get(target.strip()) or by_word.get(target.strip().lower())


# ---------------------------------------------------------------- LaTeX

_ESC = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "&": r"\&", "%": r"\%",
        "$": r"\$", "#": r"\#", "_": r"\_", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def esc(s):
    return "".join(_ESC.get(c, c) for c in s)


def render_text(text, resolve, where, errors):
    out, pos = [], 0
    for m in TOKEN.finditer(text):
        out.append(esc(text[pos:m.start()]))
        pos = m.end()
        link_text, link_target, italic, quote = m.groups()
        if link_text is not None:
            shown = link_text.strip()
            target = resolve(link_target or link_text)
            if target is None:
                errors.append(f"{where}: lenken [[{m.group(0)[2:-2]}]] peker ikke på noe ord eller id")
                out.append(esc(shown))
            elif not target["definisjon"]:
                out.append(esc(shown))  # target is hidden in the PDF
            else:
                out.append(rf"\hyperlink{{{target['id']}}}{{{esc(shown)}}}")
        elif italic is not None:
            out.append(r"\textit{" + render_text(italic, resolve, where, errors) + "}")
        else:
            out.append("``" + render_text(quote, resolve, where, errors) + "''")
    out.append(esc(text[pos:]))
    return "".join(out)


def render_entries(entries):
    resolve = resolver(entries)
    errors = []
    visible = sorted((e for e in entries if e["definisjon"]), key=lambda e: sort_key(e["ord"]))
    # Thumb-index tabs (print version): one tab per letter section, numbered from 1.
    sections = list(dict.fromkeys(section_of(e["ord"]) for e in visible))
    lines = [rf"\ordboksettabs{{{len(sections)}}}"]
    lines += [rf"\ordboktabletter{{{i}}}{{{'#' if s == NO_LETTER else s}}}"
              .replace("{#}", r"{\#}") for i, s in enumerate(sections, 1)]
    lines.append("")
    current = None
    for e in visible:
        section = section_of(e["ord"])
        if section != current:
            current = section
            # \nopagebreak keeps the letter heading on the same page as its first word
            lines += [f"\\section*{{{section}}}", rf"\ordboksetletter{{{sections.index(section) + 1}}}",
                      r"\hspace*{1em}", "", r"\nopagebreak"]
        head = []
        if e["nynorsk"]:
            head.append(f"({esc(e['nynorsk'])})")
        if e["stikkord"]:
            head.append(rf"\textit{{{esc(e['stikkord'])}}}")
        head.append(r"$\bullet$ " + render_text(e["definisjon"], resolve, e["fil"], errors))
        lines += [rf"\ordbokentry{{{e['id']}}}{{{esc(e['ord'])}}}{{{' '.join(head)}}}", ""]
    if errors:
        raise OrdbokError("\n".join(errors))
    return "\n".join(lines) + "\n"


def last_updated():
    """Date of the last commit touching ord/ (so rebuilds don't move it)."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", WORDS.name], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        day = datetime.date.fromisoformat(out)
    except (OSError, subprocess.CalledProcessError, ValueError):
        day = datetime.date.today()
    return day


def norsk_dato(day):
    return f"{day.day}. {MONTHS[day.month - 1]} {day.year}"


def render_meta():
    # `_` is special in TeX: read the URLs with it as a plain character so \href and
    # \qrcode get them verbatim.
    return (f"\\newcommand{{\\sistoppdatert}}{{{norsk_dato(last_updated())}}}\n"
            f"\\newcommand{{\\nettsidetekst}}{{{esc(NETTSIDE.split('://', 1)[-1])}}}\n"
            f"\\begingroup\\catcode`\\_=12\\relax\n"
            f"\\gdef\\nyttordurl{{{FORSLAG}}}\n"
            f"\\gdef\\nettsideqr#1{{\\qrcode[height=#1]{{{NETTSIDE}}}}}\n"
            f"\\endgroup\n")


def build(outdir, pdf=True):
    entries = load()
    outdir = Path(outdir)
    if outdir.exists():
        shutil.rmtree(outdir)
    shutil.copytree(TEMPLATE, outdir)
    shutil.copytree(ASSETS, outdir / "assets")
    (outdir / "entries.tex").write_text(render_entries(entries), encoding="utf-8")
    (outdir / "meta.tex").write_text(render_meta(), encoding="utf-8")
    if pdf:
        for root in ROOT_FILES:  # order matters: the booklet imposes ordbok-a5.pdf
            subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", root],
                           cwd=outdir, check=True)
    return entries


# ---------------------------------------------------------------- CLI

def report(exc):
    for line in str(exc).splitlines():
        if os.environ.get("GITHUB_ACTIONS"):
            m = re.match(r"(ord/[^:\s]+): ", line)
            print(f"::error file={m.group(1) if m else 'ord'}::{line}", file=sys.stderr)
        else:
            print(f"FEIL: {line}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate ord/ only")
    ap.add_argument("--tex-only", action="store_true", help="write the LaTeX sources but don't run latexmk")
    ap.add_argument("--out", default=str(ROOT / "build"), help="build directory")
    args = ap.parse_args()
    try:
        if args.check:
            entries = load()
            render_entries(entries)
        else:
            entries = build(args.out, pdf=not args.tex_only)
    except OrdbokError as exc:
        report(exc)
        sys.exit(1)
    hidden = [e["ord"] for e in entries if not e["definisjon"]]
    print(f"OK: {len(entries) - len(hidden)} ord i PDF-en, {len(hidden)} skjult (mangler definisjon)")
    if hidden:
        print("  skjult: " + ", ".join(sorted(hidden, key=sort_key)))


if __name__ == "__main__":
    main()
