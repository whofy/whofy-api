import html as html_lib

from bs4 import BeautifulSoup

BLOCK_TAGS = ["p", "li", "h1", "h2", "h3", "h4", "h5", "h6"]
MAX_BULLETS = 5
MIN_PARA_CHARS = 40


def _unescape(raw: str) -> str:
    if not raw:
        return ""
    unescaped = raw
    for _ in range(5):
        prev = unescaped
        unescaped = html_lib.unescape(prev)
        if unescaped == prev:
            break
    return unescaped


def _parse_lines(raw: str) -> list[str]:
    unescaped = _unescape(raw)
    if not unescaped:
        return []
    soup = BeautifulSoup(unescaped, "html.parser")
    lines = []
    for el in soup.find_all(BLOCK_TAGS):
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        lines.append(f"• {text}" if el.name == "li" else text)
    return lines


def _flatten(raw: str) -> str:
    unescaped = _unescape(raw)
    if not unescaped:
        return ""
    soup = BeautifulSoup(unescaped, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def full_text(raw: str) -> str:
    lines = _parse_lines(raw)
    return "\n".join(lines) if lines else _flatten(raw)


def strip_html(raw: str) -> str:
    if not raw:
        return ""
    lines = _parse_lines(raw)
    if not lines:
        return _flatten(raw)
    return "\n".join(_summarize(lines))


def first_paragraph(text: str, min_chars: int = MIN_PARA_CHARS) -> str:
    for para in text.split("\n"):
        para = para.strip()
        if len(para) >= min_chars:
            return para
    return text.strip()[:500]


def extract_bullets(html: str, max_bullets: int = MAX_BULLETS) -> list[str]:
    if not html:
        return []
    soup = BeautifulSoup(html_lib.unescape(html), "html.parser")
    bullets = []
    for li in soup.find_all("li"):
        text = li.get_text(" ", strip=True)
        if text:
            bullets.append(f"• {text}")
        if len(bullets) >= max_bullets:
            break
    return bullets


def _summarize(lines: list[str]) -> list[str]:
    out = []
    took_para = False
    bullets = 0
    in_bullets = False

    for line in lines:
        is_bullet = line.startswith("• ")
        if is_bullet:
            if bullets >= MAX_BULLETS:
                continue
            out.append(line)
            bullets += 1
            in_bullets = True
        else:
            if in_bullets:
                break
            if not took_para and len(line) >= MIN_PARA_CHARS:
                out.append(line)
                took_para = True

    return out
