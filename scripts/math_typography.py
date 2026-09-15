"""Unified Math & Typography Sanitizer.

Converts raw LaTeX formulas, unparsed fraction commands, exponents, subscripts,
and delimiters into clean, ReportLab-compatible typography and HTML tags
(<b>, <i>, <sup>, <sub>, <font>).

Used across:
  - scripts/build_cheatsheet_refined.py
  - scripts/build_cheatsheet.py
  - scripts/build_mcq_handbook.py
  - scripts/build_illustrated_book.py
  - scripts/build_structured_notes_style1.py
  - scripts/build_structured_notes_style2.py
  - scripts/build_structured_notes.py
"""
from __future__ import annotations

import html
import re


def find_matching_brace(s: str, start_idx: int) -> int:
    """Given string s and start_idx pointing to an opening '{', find the matching '}'.
    
    Returns the index of the matching '}', or -1 if unclosed.
    """
    count = 0
    for i in range(start_idx, len(s)):
        if s[i] == '{':
            count += 1
        elif s[i] == '}':
            count -= 1
            if count == 0:
                return i
    return -1


def clean_fractions(text: str) -> str:
    """Recursively parse balanced-brace fractions into arithmetic notation.
    
    Handles:
      - \\frac{A}{B}, \\dfrac{A}{B}, \\tfrac{A}{B}, and un-backslashed frac{A}{B}
      - Arbitrarily nested braces (e.g. \\frac{A_{1}}{P_{1}}, \\frac{\\frac{a}{b}}{c})
      - Mixed fractions: e.g. 16\\frac{2}{3} -> 16 2 / 3
    """
    pattern = re.compile(r'(?:\\?(?:frac|dfrac|tfrac))\s*\{')
    while True:
        m = pattern.search(text)
        if not m:
            break
        num_open = m.end() - 1
        num_close = find_matching_brace(text, num_open)
        if num_close == -1:
            break
        rest = text[num_close + 1:]
        m_den = re.match(r'^\s*\{', rest)
        if not m_den:
            break
        den_open = num_close + 1 + m_den.end() - 1
        den_close = find_matching_brace(text, den_open)
        if den_close == -1:
            break

        num = text[num_open + 1:num_close].strip()
        den = text[den_open + 1:den_close].strip()

        # Recursively parse nested fractions inside numerator and denominator
        num = clean_fractions(num)
        den = clean_fractions(den)

        has_op = lambda s: any(op in s for op in ['+', '-', '*', '=', '±', '≤', '≥', '/']) and not (s.startswith('(') and s.endswith(')'))
        num_clean = f"({num})" if has_op(num) else num
        den_clean = f"({den})" if has_op(den) else den

        # Ensure space before mixed fractions like 16 2/3
        prefix_space = ' ' if m.start() > 0 and text[m.start() - 1].isdigit() else ''
        replacement = f"{prefix_space}{num_clean} / {den_clean}"
        text = text[:m.start()] + replacement + text[den_close + 1:]

    return text


def clean_delimiters(text: str) -> str:
    """Strip LaTeX delimiter commands with or without backslashes."""
    # Slashed delimiters: \left(, \right], etc.
    text = re.sub(r'\\left\s*([(\[{|.])', r'\1', text)
    text = re.sub(r'\\right\s*([)\]}|.])', r'\1', text)
    # Unslashed delimiters: left(, right), etc.
    text = re.sub(r'(?<![a-zA-Z])left\s*\(', '(', text)
    text = re.sub(r'(?<![a-zA-Z])left\s*\[', '[', text)
    text = re.sub(r'(?<![a-zA-Z])left\s*\{', '{', text)
    text = re.sub(r'(?<![a-zA-Z])left\s*\|', '|', text)
    text = re.sub(r'right\s*\)', ')', text)
    text = re.sub(r'right\s*\]', ']', text)
    text = re.sub(r'right\s*\}', '}', text)
    text = re.sub(r'right\s*\|', '|', text)
    text = text.replace(r'\left.', '').replace(r'\right.', '')
    text = re.sub(r'(?<![a-zA-Z])left\.', '', text)
    text = re.sub(r'(?<![a-zA-Z])right\.', '', text)
    return text


def clean_subscripts_and_superscripts(text: str) -> str:
    """Convert Unicode, LaTeX, and caret/underscore notations into <sup> and <sub> tags."""
    # 1. Unicode subscripts and superscripts
    sub_map = {
        '₀': '<sub>0</sub>', '₁': '<sub>1</sub>', '₂': '<sub>2</sub>', '₃': '<sub>3</sub>', '₄': '<sub>4</sub>',
        '₅': '<sub>5</sub>', '₆': '<sub>6</sub>', '₇': '<sub>7</sub>', '₈': '<sub>8</sub>', '₉': '<sub>9</sub>',
        '₊': '<sub>+</sub>', '₋': '<sub>-</sub>',
    }
    sup_map = {
        '⁰': '<sup>0</sup>', '¹': '<sup>1</sup>', '²': '<sup>2</sup>', '³': '<sup>3</sup>', '⁴': '<sup>4</sup>',
        '⁵': '<sup>5</sup>', '⁶': '<sup>6</sup>', '⁷': '<sup>7</sup>', '⁸': '<sup>8</sup>', '⁹': '<sup>9</sup>',
        '⁺': '<sup>+</sup>', '⁻': '<sup>-</sup>', 'ⁿ': '<sup>n</sup>',
    }
    for k, v in sub_map.items():
        text = text.replace(k, v)
    for k, v in sup_map.items():
        text = text.replace(k, v)

    # 2. LaTeX braced subscripts and superscripts: _{...} and ^{...}
    text = re.sub(r'_\{([^}]+)\}', r'<sub>\1</sub>', text)
    text = re.sub(r'\^\{([^}]+)\}', r'<sup>\1</sup>', text)

    # 3. Unbraced subscripts: P_1, P_2, CP_1, Ratio (P_1 : P_2), x_i, y_n, Var_1
    text = re.sub(r'\b([A-Z]{1,3}|[xyzijkmnrtv])_([0-9]+|[a-zA-Z])\b', r'\1<sub>\2</sub>', text)
    text = re.sub(r'\b([a-zA-Z]+)_([0-9]+)\b', r'\1<sub>\2</sub>', text)

    # 4. Unbraced carets / powers: (y)^T, (y+x)^T, y^T, x^2, </sub>^t, ^t
    text = re.sub(r'\)\^([0-9a-zA-Z\+\-]+)', r')<sup>\1</sup>', text)
    text = re.sub(r'(<\/sub>)\^([0-9a-zA-Z\+\-]+)', r'\1<sup>\2</sup>', text)
    text = re.sub(r'(?<=[0-9a-zA-Z])\^([0-9a-zA-Z\+\-]+)', r'<sup>\1</sup>', text)
    text = re.sub(r'(?<=\s)\^([0-9a-zA-Z\+\-]+)', r'<sup>\1</sup>', text)

    return text


def clean_symbols(text: str) -> str:
    """Normalize Greek characters, operators, roots, and typography for Helvetica."""
    # Text macros
    text = re.sub(r'\\(?:mathrm|textbf|mathbf)\{([^}]+)\}', r'<b>\1</b>', text)
    text = re.sub(r'\\text\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\(?:mathit|textit)\{([^}]+)\}', r'<i>\1</i>', text)
    text = re.sub(r'\\sqrt\{([^}]+)\}', r'√(\1)', text)
    text = re.sub(r'\\sqrt([0-9a-zA-Z])', r'√\1', text)

    symbols = {
        r'\approx': '~', '≈': '~', r'\sim': '~', r'\neq': '!=', r'\ne': '!=', '≠': '!=',
        r'\leq': '<=', r'\le': '<=', '≤': '<=', r'\geq': '>=', r'\ge': '>=', '≥': '>=',
        r'\times': 'x', '×': 'x', r'\div': '/', '÷': '/', r'\pm': '+/-', '±': '+/-', r'\mp': '-/+',
        r'\cdot': '*', '·': '*', r'\circ': ' deg', r'\degree': ' deg', '°': ' deg', r'\infty': 'inf',
        r'\rightarrow': '&rarr;', r'\to': '&rarr;', '→': '&rarr;', r'\leftarrow': '&larr;', '←': '&larr;',
        r'\leftrightarrow': '&harr;', '↔': '&harr;',
        r'\Rightarrow': '=>', r'\Leftarrow': '<=', r'\Leftrightarrow': '<=>',
        r'\pi': 'pi', r'\theta': 'theta', r'\alpha': 'alpha', r'\beta': 'beta',
        r'\gamma': 'gamma', r'\Delta': 'Delta', r'\delta': 'delta', r'\lambda': 'lambda',
        r'\mu': 'mu', r'\sigma': 'sigma', r'\omega': 'omega', r'\Omega': 'Omega',
        r'\phi': 'phi', r'\rho': 'rho', r'\tau': 'tau', r'\epsilon': 'epsilon',
        r'\sum': 'SUM', r'\prod': 'PROD', r'\int': 'INT',
    }
    for k, v in symbols.items():
        if k.startswith('\\'):
            text = re.sub(re.escape(k) + r'(?![a-zA-Z])', v, text)
        else:
            text = text.replace(k, v)

    return text


def sanitize_math_typography(text: str) -> str:
    """Master pipeline to convert raw mathematical markdown/LaTeX into clean ReportLab typography.
    
    Transforms:
      - \\frac{A_{1}}{P_{1}} -> A<sub>1</sub> / P<sub>1</sub>
      - (y)^T : (y+x)^T -> (y)<sup>T</sup> : (y+x)<sup>T</sup>
      - CI_{Units} = (y+x)^T - y^T -> CI<sub>Units</sub> = (y+x)<sup>T</sup> - y<sup>T</sup>
      - left(frac{A_{1}}{P_{1}}right)^t -> (A<sub>1</sub> / P<sub>1</sub>)<sup>t</sup>
      - P_1^t -> P<sub>1</sub><sup>t</sup>
      - R\\% -> R%
      - x^2 + y^2 = z^2 -> x<sup>2</sup> + y<sup>2</sup> = z<sup>2</sup>
    """
    if not text:
        return ""

    # 0. Protect backtick inline code spans
    code_blocks: list[str] = []
    def save_code(m: re.Match) -> str:
        code_blocks.append(m.group(0))
        return f"__CODE_BLOCK_{len(code_blocks)-1}__"
    text = re.sub(r"`[^`]+`", save_code, text)

    # 1. Pre-decode HTML entities and strip math dollar delimiters
    text = html.unescape(str(text))
    text = text.replace("$$", " ").replace("$", "")

    # 2. Delimiter normalization (\left, \right, left(, right))
    text = clean_delimiters(text)

    # 3. Clean set brackets, spacing, and arrows
    text = text.replace(r'\{', '{').replace(r'\}', '}')
    text = re.sub(r'\\(?:q?quad)', '  ', text)
    text = text.replace(r'\,', ' ').replace(r'\;', ' ').replace(r'\:', ' ')
    text = re.sub(r'\\xrightarrow(?:\[(.*?)\])?\{(.*?)\}', r' -> [\2] -> ', text)

    # 4. Text macros, roots, and Greek/operator symbols
    text = clean_symbols(text)

    # 5. Balanced-brace fractions (clean_fractions)
    text = clean_fractions(text)

    # 6. Subscripts and superscripts (powers, squares, subscripts)
    text = clean_subscripts_and_superscripts(text)

    # 7. Clean escaped backslashes: \%, \$, \_, \#, \&, \(, \), \[, \], \{, \}, \|
    text = re.sub(r'\\([%$#&_()\[\]{}|])', r'\1', text)
    # Strip any dangling LaTeX backslashes before words
    text = re.sub(r'\\([a-zA-Z]+)', r'\1', text)

    # 8. Restore code blocks
    for i, block in enumerate(code_blocks):
        text = text.replace(f"__CODE_BLOCK_{i}__", block)

    return text
