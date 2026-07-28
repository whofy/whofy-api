import re

_TECH_WHITELIST = re.compile(
    r"\b(?:"
    r"software|developer|engineer|engineering|programmer|coding|"
    r"frontend|front[\s-]?end|backend|back[\s-]?end|fullstack|full[\s-]?stack|"
    r"devops|dev[\s-]?ops|sre|site[\s-]?reliability|"
    r"data[\s-]?(?:scientist|engineer|analyst|architect)|"
    r"machine[\s-]?learning|ml[\s-]?engineer|ai[\s-]?engineer|"
    r"cloud|infrastructure|platform[\s-]?engineer|"
    r"security[\s-]?engineer|cybersecurity|infosec|"
    r"qa|quality[\s-]?assurance|test[\s-]?engineer|sdet|automation[\s-]?engineer|"
    r"mobile[\s-]?(?:developer|engineer)|ios[\s-]?(?:developer|engineer)|android[\s-]?(?:developer|engineer)|"
    r"web[\s-]?developer|ui[\s-]?(?:developer|engineer)|ux[\s-]?(?:designer|researcher|engineer)|"
    r"product[\s-]?(?:manager|owner|designer)|technical[\s-]?(?:program|project)[\s-]?manager|"
    r"scrum[\s-]?master|agile[\s-]?coach|"
    r"system[\s-]?(?:admin|administrator|engineer|architect)|"
    r"network[\s-]?engineer|database[\s-]?(?:admin|administrator|engineer)|dba|"
    r"solutions[\s-]?architect|technical[\s-]?architect|"
    r"embedded[\s-]?(?:engineer|developer)|firmware|"
    r"blockchain|smart[\s-]?contract|web3|"
    r"it[\s-]?(?:manager|analyst|support|specialist|administrator|consultant|coordinator)|"
    r"technical[\s-]?(?:lead|writer|support|consultant)|tech[\s-]?lead|"
    r"release[\s-]?engineer|build[\s-]?engineer|"
    r"data[\s-]?(?:ops|pipeline)|etl|bi[\s-]?(?:developer|analyst|engineer)|"
    r"game[\s-]?developer|graphics[\s-]?(?:programmer|engineer)|"
    r"nlp|computer[\s-]?vision|robotics[\s-]?engineer|"
    r"erp|sap[\s-]?(?:consultant|developer|analyst)|salesforce|"
    r"help[\s-]?desk|desktop[\s-]?support|"
    r"(?:python|java|golang|rust|ruby|php|react|angular|vue|node|\.net|c\+\+|c#|swift|kotlin)"
    r")\b",
    re.IGNORECASE,
)

_NON_TECH_BLACKLIST = re.compile(
    r"\b(?:"
    r"nurse|nursing|physician|doctor|surgeon|pharmacist|therapist|"
    r"dentist|dental|veterinar|optometrist|radiolog|"
    r"medical[\s-]?(?:assistant|technician|officer|director|billing)|"
    r"clinical[\s-]?(?:research|trial|coordinator|specialist)|"
    r"registered[\s-]?nurse|lpn|rn[\s-]|cna[\s-]|"
    r"accountant|accounting|bookkeeper|auditor|tax[\s-]?(?:manager|analyst|specialist)|"
    r"financial[\s-]?(?:advisor|planner|controller)|cpa[\s-]|"
    r"attorney|lawyer|paralegal|legal[\s-]?(?:assistant|counsel|secretary)|"
    r"chef|cook|sous[\s-]?chef|pastry|culinar|"
    r"truck[\s-]?driver|cdl|forklift|warehouse[\s-]?(?:associate|worker)|"
    r"janitor|custodian|housekeeper|cleaning|"
    r"cashier|retail[\s-]?(?:associate|clerk|sales)|store[\s-]?(?:manager|associate)|"
    r"barista|waiter|waitress|bartender|host(?:ess)?|busser|"
    r"plumber|electrician|hvac|carpenter|welder|mechanic|"
    r"real[\s-]?estate|mortgage[\s-]?(?:loan|officer)|"
    r"social[\s-]?worker|counselor|psychologist|"
    r"teacher|professor|tutor|instructor|"
    r"police|firefighter|correctional[\s-]?officer|"
    r"insurance[\s-]?(?:agent|adjuster|underwriter)|"
    r"loan[\s-]?(?:officer|processor)|bank[\s-]?teller|"
    r"receptionist|administrative[\s-]?assistant|office[\s-]?(?:manager|clerk)|"
    r"construction[\s-]?(?:worker|manager|superintendent)|"
    r"speech[\s-]?(?:pathologist|therapist)|occupational[\s-]?therapist|"
    r"physical[\s-]?therapist|chiropractor"
    r")\b",
    re.IGNORECASE,
)


def is_tech_job(title: str, description: str = "") -> bool:
    if _NON_TECH_BLACKLIST.search(title):
        return False
    if _TECH_WHITELIST.search(title):
        return True
    if description and _TECH_WHITELIST.search(description[:500]):
        return True
    return False


def filter_tech_jobs(jobs: list[dict]) -> list[dict]:
    return [j for j in jobs if is_tech_job(j.get("title", ""), j.get("description", ""))]
