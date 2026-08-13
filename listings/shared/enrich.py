import re
from pathlib import Path
import yaml

REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)
HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)
ONSITE_RE = re.compile(r"\b(?:on[\s-]?site|in[\s-]?office|in[\s-]?person)\b", re.IGNORECASE)

_YEARS_RE = re.compile(r"(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE)
_SENIOR_RE = re.compile(r"\b(?:senior|sr\.?|staff|principal|lead|director|head)\b", re.IGNORECASE)
_JUNIOR_RE = re.compile(r"\b(?:junior|jr\.?|associate)\b", re.IGNORECASE)
_INTERN_RE = re.compile(r"\b(?:intern|internship|trainee|apprentice|co-?op)\b", re.IGNORECASE)
_ENTRY_RE = re.compile(r"\b(?:entry[\s-]?level|graduate|fresher|new[\s-]?grad)\b", re.IGNORECASE)

# ── Skill vocabulary loaded from data/skills.yml ──
# To add or remove a skill, edit data/skills.yml — no code change needed.
# case_sensitive: short/ambiguous names ("C", "R", "Go") matched with exact case only
# to prevent false positives on common English words.
_SKILLS_YML = Path(__file__).parent.parent.parent / 'data' / 'skills.yml'
_skills_data = yaml.safe_load(_SKILLS_YML.read_text(encoding='utf-8'))
SKILL_VOCAB = _skills_data['skills']
_CASE_SENSITIVE_SKILLS = set(_skills_data['case_sensitive'])
_UNIQUE_SKILLS = list(dict.fromkeys(SKILL_VOCAB))

_CASE_INSENSITIVE_SKILLS = [s for s in _UNIQUE_SKILLS if s not in _CASE_SENSITIVE_SKILLS]

_SKILL_PATTERN_CI = re.compile(
    r"(?<![a-zA-Z0-9_])(?:" + "|".join(re.escape(s) for s in sorted(_CASE_INSENSITIVE_SKILLS, key=len, reverse=True)) + r")(?![a-zA-Z0-9_+#])",
    re.IGNORECASE,
)
_SKILL_PATTERN_CS = re.compile(
    r"(?<![a-zA-Z0-9_])(?:" + "|".join(re.escape(s) for s in sorted(_CASE_SENSITIVE_SKILLS, key=len, reverse=True)) + r")(?![a-zA-Z0-9_+#])",
)

_SKILL_CANONICAL = {s.lower(): s for s in _UNIQUE_SKILLS}

MAX_EXTRACTED_SKILLS = 15


def detect_work_type(title: str, location: str, description: str) -> str:
    text = f"{title} {location}"
    if HYBRID_RE.search(text):
        return "Hybrid"
    if REMOTE_RE.search(text):
        return "Remote"
    if ONSITE_RE.search(text):
        return "On-site"
    desc_head = description[:500] if description else ""
    if HYBRID_RE.search(desc_head):
        return "Hybrid"
    if REMOTE_RE.search(desc_head):
        return "Remote"
    if ONSITE_RE.search(desc_head):
        return "On-site"
    return "On-site"


def detect_experience(title: str, description: str) -> str:
    if _INTERN_RE.search(title):
        return "Internship"
    if _ENTRY_RE.search(title):
        return "Entry Level"
    if _JUNIOR_RE.search(title):
        return "Junior"
    if _SENIOR_RE.search(title):
        return "Senior"

    desc_head = description[:800] if description else ""
    m = _YEARS_RE.search(desc_head)
    if m:
        yrs = int(m.group(1))
        if yrs <= 1:
            return "Entry Level"
        if yrs <= 3:
            return "Junior"
        if yrs <= 6:
            return "Mid Level"
        return "Senior"

    if _INTERN_RE.search(desc_head):
        return "Internship"
    if _ENTRY_RE.search(desc_head):
        return "Entry Level"
    if _JUNIOR_RE.search(desc_head):
        return "Junior"
    if _SENIOR_RE.search(desc_head):
        return "Senior"

    return "Mid Level"


def extract_required_skills(title: str, description: str) -> list[str]:
    combined = f"{title} {description}"
    found = []
    seen = set()

    for m in _SKILL_PATTERN_CI.finditer(combined):
        canonical = _SKILL_CANONICAL.get(m.group().lower())
        if canonical and canonical not in seen:
            seen.add(canonical)
            found.append(canonical)
            if len(found) >= MAX_EXTRACTED_SKILLS: break

    if len(found) < MAX_EXTRACTED_SKILLS:
        for m in _SKILL_PATTERN_CS.finditer(combined):
            canonical = m.group()
            if canonical in _CASE_SENSITIVE_SKILLS and canonical not in seen:
                seen.add(canonical)
                found.append(canonical)
                if len(found) >= MAX_EXTRACTED_SKILLS: break
    return found


def bake_required_skills(description: str, required_skills: list[str]) -> str:
    if not required_skills:
        return description
    block = "Required skills:\n" + "\n".join(f"• {s}" for s in required_skills)
    return f"{description}\n\n{block}" if description else block
