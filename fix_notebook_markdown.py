#!/usr/bin/env python3
"""
Fix markdown cells in htm_classification_report.ipynb:
- Convert HTML to standard markdown
- Ensure LaTeX expressions render correctly ($...$ and $$...$$)
"""

import json
import re
import html
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString

NB_PATH = Path(__file__).with_name("htm_classification_report.ipynb")


def decode_latex(text: str) -> str:
    """Decode HTML entities in LaTeX so Jupyter/MathJax can render them."""
    return (
        text.replace("&amp;", "&")
        .replace("&gt;", ">")
        .replace("&lt;", "<")
        .replace("&le;", "≤")
        .replace("&ge;", "≥")
        .replace("&times;", "×")
        .replace("&#39;", "'")
    )


def html_to_markdown(html_src: str) -> str:
    """
    Convert HTML to clean markdown. Preserves LaTeX blocks and decodes entities.
    """
    # Protect LaTeX blocks before parsing (so we don't mangle them)
    latex_blocks = []
    def save_latex(m):
        latex_blocks.append(decode_latex(m.group(0)))
        return f"\n__LATEX_BLOCK_{len(latex_blocks)-1}__\n"

    # Match $$...$$ (block) and $...$ (inline) - be careful with nested $
    # Block math: $$ ... $$ (non-greedy)
    html_src = re.sub(r"\$\$([\s\S]*?)\$\$", save_latex, html_src)
    # Inline math: $ ... $ (avoid matching across line breaks for block)
    html_src = re.sub(r"(?<!\$)\$([^$\n]+)\$(?!\$)", save_latex, html_src)

    soup = BeautifulSoup(html_src, "html.parser")

    # Remove anchor links
    for a in soup.find_all("a", class_="anchor-link"):
        a.decompose()

    parts = []

    def process(el):
        if isinstance(el, NavigableString):
            t = str(el).strip()
            if t:
                parts.append(t)
            return

        if el.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(el.name[1])
            parts.append("\n" + "#" * level + " " + el.get_text().strip() + "\n")
            return

        if el.name == "p":
            inner = []
            for child in el.children:
                if isinstance(child, NavigableString):
                    inner.append(str(child))
                else:
                    inner.append(process_elem(child))
            text = "".join(inner).strip()
            if text:
                parts.append(text + "\n\n")
            return

        if el.name == "strong":
            return "**" + el.get_text() + "**"

        if el.name == "em":
            return "*" + el.get_text() + "*"

        if el.name == "code":
            return "`" + el.get_text() + "`"

        if el.name == "ul":
            for li in el.find_all("li", recursive=False):
                parts.append("- " + process_li(li) + "\n")
            return

        if el.name == "ol":
            for i, li in enumerate(el.find_all("li", recursive=False), 1):
                parts.append(f"{i}. " + process_li(li) + "\n")
            return

        if el.name == "table":
            parts.append(process_table(el))
            return

        if el.name == "pre":
            code = el.find("code")
            content = code.get_text() if code else el.get_text()
            parts.append("\n```\n" + content.strip() + "\n```\n\n")
            return

        if el.name == "hr":
            parts.append("\n---\n\n")
            return

        # Default: recurse
        for child in el.children:
            process(child)

    def process_elem(el):
        if isinstance(el, NavigableString):
            return str(el)
        if el.name == "strong":
            return "**" + el.get_text() + "**"
        if el.name == "em":
            return "*" + el.get_text() + "*"
        if el.name == "code":
            return "`" + el.get_text() + "`"
        if el.name == "a" and not el.get("class"):
            return "[" + el.get_text() + "](" + (el.get("href") or "") + ")"
        buf = []
        for c in el.children:
            buf.append(process_elem(c) if hasattr(c, "name") else str(c))
        return "".join(buf)

    def process_li(li):
        buf = []
        for c in li.children:
            if isinstance(c, NavigableString):
                buf.append(str(c))
            else:
                buf.append(process_elem(c))
        return "".join(buf).strip()

    def process_table(table):
        rows = []
        thead = table.find("thead")
        if thead:
            headers = [th.get_text().strip() for th in thead.find_all(["th", "td"])]
            rows.append("| " + " | ".join(headers) + " |")
            rows.append("| " + " | ".join(["---"] * len(headers)) + " |")
        tbody = table.find("tbody")
        if tbody:
            for tr in tbody.find_all("tr"):
                cells = []
                for td in tr.find_all(["td", "th"]):
                    cells.append(process_elem(td).replace("|", "\\|").strip())
                rows.append("| " + " | ".join(cells) + " |")
        return "\n" + "\n".join(rows) + "\n\n"

    # Process top-level elements
    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "table", "pre", "hr"]):
        if el.parent == soup or el.parent.name in ("body", "div"):
            process(el)

    # If nothing matched (e.g. div with mixed content), process body
    if not parts:
        for el in soup.children:
            if hasattr(el, "name") and el.name:
                process(el)

    md = "".join(p for p in parts if p is not None)

    # Restore LaTeX blocks
    for i, latex in enumerate(latex_blocks):
        md = md.replace(f"__LATEX_BLOCK_{i}__", latex)

    # Clean up extra newlines
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md


def fix_first_cell(html_src: str) -> str:
    """First cell has Quarto YAML - convert to a simple title + intro."""
    soup = BeautifulSoup(html_src, "html.parser")
    for a in soup.find_all("a", class_="anchor-link"):
        a.decompose()

    # Get the main content after the YAML-style header
    text = soup.get_text(separator="\n")
    # Find "1. Introduction" and take from there
    if "1. Introduction" in text:
        idx = text.index("1. Introduction")
        intro = text[idx:]
    else:
        intro = text

    # Build clean markdown
    lines = [
        "# Hand-to-Mouth Agent Classification for Brazil",
        "",
        "*Kaplan–Violante–Weidner Framework Applied to POF 2017–18 and PNADC*",
        "",
        "---",
        "",
        "## 1. Introduction",
        "",
    ]
    # Parse the introduction paragraph
    for a in soup.find_all(["h2", "p", "ul"]):
        if "Introduction" in a.get_text():
            continue  # skip the h2 we already added
        if a.name == "p":
            lines.append(a.get_text().strip())
            lines.append("")
        elif a.name == "ul":
            for li in a.find_all("li"):
                lines.append("- " + li.get_text().strip())
            lines.append("")

    return "\n".join(lines).strip()


def source_lines(text: str) -> list:
    """Split into notebook source list (lines with \\n except last)."""
    lines = text.split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return [""]
    return [l + "\n" for l in lines[:-1]] + [lines[-1]]


def main():
    print(f"Loading {NB_PATH.name} …")
    nb = json.loads(NB_PATH.read_text(encoding="utf-8"))

    for i, cell in enumerate(nb["cells"]):
        if cell["cell_type"] != "markdown":
            continue

        src = "".join(cell["source"])
        if not src.strip():
            continue

        # First cell: special handling (Quarto YAML + intro)
        if i == 0:
            fixed = fix_first_cell(src)
        else:
            fixed = html_to_markdown(src)

        cell["source"] = source_lines(fixed)
        print(f"  Fixed markdown cell {i}")

    NB_PATH.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Saved → {NB_PATH.name}")


if __name__ == "__main__":
    main()
