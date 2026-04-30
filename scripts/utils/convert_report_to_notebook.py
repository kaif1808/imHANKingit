#!/usr/bin/env python3
"""
Convert htm_classification_report.html → htm_classification_report.ipynb

Parses the JupyterLab-style HTML export produced by nbconvert, extracts all
markdown and code cells (with their HTML-table and PNG-image outputs), and
writes a valid nbformat 4.5 notebook JSON file.
"""

import json
import re
import html
from pathlib import Path
from bs4 import BeautifulSoup, Tag

HTML_FILE = Path(__file__).with_name("htm_classification_report.html")
OUT_FILE  = Path(__file__).with_name("htm_classification_report.ipynb")

OLD_BASE_DIR = "/Users/matt/Library/CloudStorage/OneDrive-Personal/BSE/term_2/thesis/data"
NEW_BASE_DIR = "/Users/kai/Desktop/imHANKingit"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def strip_spans(pre_tag: Tag) -> str:
    """Return plain text from a syntax-highlighted <pre> block."""
    return html.unescape(pre_tag.get_text())


def source_lines(text: str) -> list[str]:
    """Split code/markdown text into notebook source list (lines end with \\n
    except the last)."""
    lines = text.split("\n")
    # drop trailing blank lines
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return [""]
    result = [l + "\n" for l in lines[:-1]] + [lines[-1]]
    return result


def html_output(div: Tag) -> dict:
    """Build an execute_result output from an HTML-rendered output div."""
    inner = div.decode_contents().strip()
    return {
        "output_type": "execute_result",
        "metadata": {},
        "execution_count": None,
        "data": {
            "text/html": source_lines(inner),
            "text/plain": ["<pandas DataFrame>"],
        },
    }


def image_output(img_tag: Tag) -> dict:
    """Build an execute_result output from a base64 PNG img tag."""
    src = img_tag.get("src", "")
    # src = "data:image/png;base64,<data>"
    prefix = "data:image/png;base64,"
    b64 = src[len(prefix):] if src.startswith(prefix) else src
    return {
        "output_type": "execute_result",
        "metadata": {},
        "execution_count": None,
        "data": {
            "image/png": b64,
            "text/plain": ["<matplotlib figure>"],
        },
    }


def stream_output(pre_tag: Tag) -> dict:
    """Build a stream output from a plain-text <pre> block."""
    text = html.unescape(pre_tag.get_text())
    return {
        "output_type": "stream",
        "name": "stdout",
        "text": source_lines(text),
    }


def extract_markdown(cell_div: Tag) -> str:
    """
    Extract markdown source from a jp-MarkdownCell.

    The rendered HTML is inside jp-RenderedMarkdown. We convert the rendered
    HTML back to a reasonable markdown approximation so the notebook is
    editable, but for complex tables we fall back to HTML (which Jupyter
    renders fine in markdown cells).
    """
    rendered = cell_div.find(class_="jp-RenderedMarkdown")
    if rendered is None:
        return ""
    return rendered.decode_contents().strip()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def convert(html_path: Path, out_path: Path) -> None:
    print(f"Reading {html_path.name} …")
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")

    cells = []

    for cell_div in soup.find_all("div", class_="jp-Cell"):
        classes = cell_div.get("class", [])

        # Strip "cell-id=" prefix to get a valid nbformat cell id
        raw_id = cell_div.get("id", "")
        cell_id = re.sub(r"^cell-id=", "", raw_id) or None

        # ── Markdown cell ────────────────────────────────────────────────
        if "jp-MarkdownCell" in classes:
            md_source = extract_markdown(cell_div)
            if not md_source:
                continue
            cell = {
                "cell_type": "markdown",
                "metadata": {},
                "source": source_lines(md_source),
            }
            if cell_id:
                cell["id"] = cell_id
            cells.append(cell)

        # ── Code cell ────────────────────────────────────────────────────
        elif "jp-CodeCell" in classes:
            # --- source code ---
            pre_tag = cell_div.find("div", class_="highlight")
            if pre_tag is None:
                continue
            code_text = strip_spans(pre_tag.find("pre") or pre_tag)
            # Fix BASE_DIR path
            code_text = code_text.replace(OLD_BASE_DIR, NEW_BASE_DIR)
            # Remove a stray line `SCRIPT = BASE_DIR / "kai" / "htm_classification.py"`
            # (the script reference from the report notebook's cell 1)
            code_text = re.sub(
                r'SCRIPT\s*=\s*BASE_DIR\s*/\s*"kai"\s*/\s*"htm_classification\.py"\n?',
                "",
                code_text,
            )

            # --- execution count ---
            prompt = cell_div.find("div", class_="jp-InputPrompt")
            exec_count = None
            if prompt:
                m = re.search(r"\[(\d+)\]", prompt.get_text())
                if m:
                    exec_count = int(m.group(1))

            # --- outputs ---
            outputs = []
            output_wrapper = cell_div.find("div", class_="jp-Cell-outputWrapper")
            if output_wrapper:
                for out_child in output_wrapper.find_all(
                    "div", class_="jp-OutputArea-child"
                ):
                    # HTML (dataframe tables)
                    html_out = out_child.find(
                        "div", class_=lambda c: c and "jp-RenderedHTML" in c
                    )
                    if html_out:
                        o = html_output(html_out)
                        o["execution_count"] = exec_count
                        outputs.append(o)
                        continue

                    # PNG images
                    img_div = out_child.find("div", class_="jp-RenderedImage")
                    if img_div:
                        img_tag = img_div.find("img")
                        if img_tag:
                            o = image_output(img_tag)
                            o["execution_count"] = exec_count
                            outputs.append(o)
                            continue

                    # Plain text (stream / stdout)
                    text_div = out_child.find(
                        "div", class_=lambda c: c and "jp-RenderedText" in c
                    )
                    if text_div:
                        pre = text_div.find("pre")
                        if pre:
                            outputs.append(stream_output(pre))
                        continue

            cell = {
                "cell_type": "code",
                "metadata": {},
                "source": source_lines(code_text),
                "outputs": outputs,
                "execution_count": exec_count,
            }
            if cell_id:
                cell["id"] = cell_id
            cells.append(cell)

    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "version": "3.11.0",
            },
        },
        "cells": cells,
    }

    print(f"Extracted {len(cells)} cells "
          f"({sum(1 for c in cells if c['cell_type']=='markdown')} markdown, "
          f"{sum(1 for c in cells if c['cell_type']=='code')} code)")

    out_path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Written → {out_path.name}")


if __name__ == "__main__":
    convert(HTML_FILE, OUT_FILE)
