import re

REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)
HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)
ONSITE_RE = re.compile(r"\b(?:on[\s-]?site|in[\s-]?office|in[\s-]?person)\b", re.IGNORECASE)

_YEARS_RE = re.compile(r"(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE)
_SENIOR_RE = re.compile(r"\b(?:senior|sr\.?|staff|principal|lead|director|head)\b", re.IGNORECASE)
_JUNIOR_RE = re.compile(r"\b(?:junior|jr\.?|associate)\b", re.IGNORECASE)
_INTERN_RE = re.compile(r"\b(?:intern|internship|trainee|apprentice|co-?op)\b", re.IGNORECASE)
_ENTRY_RE = re.compile(r"\b(?:entry[\s-]?level|graduate|fresher|new[\s-]?grad)\b", re.IGNORECASE)

# Curated skill vocabulary for regex-based extraction from job postings.
# Deliberately not calling an LLM per job here — this runs over every job on
# every ingestion cycle, so it needs to be fast and free. Canonical casing is
# what gets shown to the user.
SKILL_VOCAB = [
    "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Go", "Golang",
    "Rust", "Ruby", "PHP", "Kotlin", "Swift", "Scala", "R", "MATLAB",
    "React", "Angular", "Vue", "Svelte", "Next.js", "Node.js", "Express",
    "Django", "Flask", "FastAPI", "Spring", "Spring Boot", "Rails", ".NET",
    "GraphQL", "REST", "gRPC", "Redux", "Tailwind", "HTML", "CSS", "Sass",
    "SQL", "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch",
    "Cassandra", "DynamoDB", "SQLite", "Oracle",
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform", "Ansible",
    "Jenkins", "CI/CD", "Git", "Linux", "Nginx", "Kafka", "RabbitMQ",
    "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch", "Keras",
    "Scikit-learn", "Pandas", "NumPy", "NLP", "Computer Vision", "LLM",
    "Data Science", "Data Engineering", "ETL", "Spark", "Hadoop", "Airflow",
    "iOS", "Android", "React Native", "Flutter", "Objective-C",
    "Jest", "Cypress", "Selenium", "Pytest", "JUnit",
    "Microservices", "System Design", "Distributed Systems",
    "Figma", "Sketch", "UI/UX",
    "Salesforce", "Tableau", "Power BI", "Excel", "Jira",
    "Solidity", "Blockchain", "Web3",
]
_SKILL_RES = [(skill, re.compile(r"\b" + re.escape(skill) + r"\b", re.IGNORECASE)) for skill in SKILL_VOCAB]

MAX_EXTRACTED_SKILLS = 10


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
    haystack = f"{title} {description}"
    found = []
    for skill, pattern in _SKILL_RES:
        if pattern.search(haystack):
            found.append(skill)
        if len(found) >= MAX_EXTRACTED_SKILLS:
            break
    return found


def bake_required_skills(description: str, required_skills: list[str]) -> str:
    """Append the extracted skills onto the (short, display) description so
    they're part of the stored/indexed text — otherwise a skill only
    mentioned in a section that strip_html() truncated away would be
    invisible to both the UI and $text search."""
    if not required_skills:
        return description
    block = "Required skills:\n" + "\n".join(f"• {s}" for s in required_skills)
    return f"{description}\n\n{block}" if description else block
