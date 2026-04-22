#!/usr/bin/env python3
"""Markdown → PDF with CJK support via fpdf2 + Microsoft YaHei.

Supports the markdown subset used in this project:
  - # / ## / ### headings
  - paragraphs
  - tables (GFM pipe syntax)
  - unordered lists (- / *)
  - ordered lists (1.)
  - **bold** and `code` inline
  - fenced ``` code blocks
  - --- horizontal rule
"""
import argparse, os, re, sys
from fpdf import FPDF

FONT_REG  = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

H1_SIZE, H2_SIZE, H3_SIZE = 18, 14, 12
BODY_SIZE = 10.5
CODE_SIZE = 9.5
LINE_H    = 5.5

INLINE_RE = re.compile(r'(\*\*[^*]+?\*\*|`[^`]+?`)')

def inline(pdf, text):
    """Write a single logical line handling **bold** and `code`."""
    for chunk in INLINE_RE.split(text):
        if not chunk:
            continue
        if chunk.startswith('**') and chunk.endswith('**'):
            pdf.set_font('yahei', 'B', BODY_SIZE)
            pdf.write(LINE_H, chunk[2:-2])
            pdf.set_font('yahei', '', BODY_SIZE)
        elif chunk.startswith('`') and chunk.endswith('`'):
            pdf.set_font('yahei', '', CODE_SIZE)
            pdf.write(LINE_H, chunk[1:-1])
            pdf.set_font('yahei', '', BODY_SIZE)
        else:
            pdf.write(LINE_H, chunk)

def strip_inline(s):
    """Remove inline markers for table cells (fpdf2 table cells are plain)."""
    s = re.sub(r'\*\*([^*]+?)\*\*', r'\1', s)
    s = re.sub(r'`([^`]+?)`',      r'\1', s)
    return s

def parse_table(lines, i):
    """Return (rows_of_cells, next_i). lines[i] is header, lines[i+1] is sep."""
    def split_row(s):
        s = s.strip()
        if s.startswith('|'): s = s[1:]
        if s.endswith('|'):   s = s[:-1]
        return [c.strip() for c in s.split('|')]
    rows = [split_row(lines[i])]
    j = i + 2  # skip header + separator
    while j < len(lines) and lines[j].strip().startswith('|'):
        rows.append(split_row(lines[j]))
        j += 1
    return rows, j

def render_heading(pdf, level, text):
    size = {1: H1_SIZE, 2: H2_SIZE, 3: H3_SIZE}.get(level, BODY_SIZE)
    pdf.ln(3 if level <= 2 else 1)
    pdf.set_font('yahei', 'B', size)
    pdf.write(size * 0.5, strip_inline(text))
    pdf.ln(size * 0.55)
    pdf.set_font('yahei', '', BODY_SIZE)
    pdf.ln(1)

def render_table(pdf, rows):
    if not rows: return
    ncol = max(len(r) for r in rows)
    W = pdf.w - pdf.l_margin - pdf.r_margin
    col_w = [W/ncol] * ncol
    pdf.set_font('yahei', '', BODY_SIZE - 0.5)
    with pdf.table(col_widths=col_w, text_align='LEFT',
                   line_height=LINE_H, padding=1) as table:
        for r_idx, row in enumerate(rows):
            padded = list(row) + [''] * (ncol - len(row))
            trow = table.row()
            for c_idx, cell in enumerate(padded):
                trow.cell(strip_inline(cell))
    pdf.set_font('yahei', '', BODY_SIZE)
    pdf.ln(1)

def render_code(pdf, code_lines):
    pdf.set_font('yahei', '', CODE_SIZE)
    pdf.set_fill_color(240, 240, 240)
    W = pdf.w - pdf.l_margin - pdf.r_margin
    for ln in code_lines:
        pdf.cell(W, LINE_H, ln, fill=True, new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('yahei', '', BODY_SIZE)
    pdf.ln(1)

def render_list_item(pdf, marker, text):
    pdf.set_x(pdf.l_margin + 3)
    pdf.write(LINE_H, marker + ' ')
    inline(pdf, text)
    pdf.ln(LINE_H)

def render_paragraph(pdf, buf):
    text = ' '.join(buf).strip()
    if not text: return
    inline(pdf, text)
    pdf.ln(LINE_H)
    pdf.ln(1)

def render(pdf, md_text):
    lines = md_text.splitlines()
    i = 0
    in_code = False
    code_buf = []
    para_buf = []
    while i < len(lines):
        ln = lines[i]
        # fenced code block
        if ln.strip().startswith('```'):
            if para_buf: render_paragraph(pdf, para_buf); para_buf = []
            if not in_code:
                in_code = True
                code_buf = []
            else:
                render_code(pdf, code_buf)
                in_code = False
                code_buf = []
            i += 1
            continue
        if in_code:
            code_buf.append(ln)
            i += 1
            continue
        # heading
        m = re.match(r'^(#{1,3})\s+(.*)$', ln)
        if m:
            if para_buf: render_paragraph(pdf, para_buf); para_buf = []
            render_heading(pdf, len(m.group(1)), m.group(2))
            i += 1
            continue
        # horizontal rule
        if re.match(r'^\s*---+\s*$', ln):
            if para_buf: render_paragraph(pdf, para_buf); para_buf = []
            pdf.ln(1)
            W = pdf.w - pdf.l_margin - pdf.r_margin
            pdf.set_draw_color(180, 180, 180)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.l_margin + W, y)
            pdf.ln(3)
            i += 1
            continue
        # table: starts with `|` AND line i+1 is the separator
        if ln.strip().startswith('|') and i + 1 < len(lines) \
                and re.match(r'^\s*\|?[\s:\-\|]+\|?\s*$', lines[i+1]) \
                and '---' in lines[i+1]:
            if para_buf: render_paragraph(pdf, para_buf); para_buf = []
            rows, i = parse_table(lines, i)
            render_table(pdf, rows)
            continue
        # unordered list
        m = re.match(r'^\s*[-*]\s+(.*)$', ln)
        if m:
            if para_buf: render_paragraph(pdf, para_buf); para_buf = []
            render_list_item(pdf, '•', m.group(1))
            i += 1
            continue
        # ordered list
        m = re.match(r'^\s*(\d+)\.\s+(.*)$', ln)
        if m:
            if para_buf: render_paragraph(pdf, para_buf); para_buf = []
            render_list_item(pdf, f"{m.group(1)}.", m.group(2))
            i += 1
            continue
        # blank line → paragraph break
        if not ln.strip():
            if para_buf: render_paragraph(pdf, para_buf); para_buf = []
            i += 1
            continue
        # default: accumulate into paragraph
        para_buf.append(ln.strip())
        i += 1
    if para_buf: render_paragraph(pdf, para_buf)
    if in_code and code_buf: render_code(pdf, code_buf)

def convert(md_path, pdf_path):
    with open(md_path, encoding='utf-8') as f:
        md_text = f.read()
    pdf = FPDF(format='A4', unit='mm')
    pdf.set_margin(18)
    pdf.add_font('yahei', style='',  fname=FONT_REG)
    pdf.add_font('yahei', style='B', fname=FONT_BOLD)
    pdf.set_font('yahei', '', BODY_SIZE)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    render(pdf, md_text)
    pdf.output(pdf_path)
    print(f"wrote {pdf_path}  ({os.path.getsize(pdf_path):,} bytes)")

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('md')
    ap.add_argument('pdf')
    args = ap.parse_args()
    convert(args.md, args.pdf)
