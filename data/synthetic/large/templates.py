"""Templates for routine / administrative pages in large synthetic claim files. All content is fictional."""
import random

from cases_def import visit  # reuse the clinical note layout

CPT = [("99213", "Office visit, established, low complexity", 128.00), ("99214", "Office visit, established, moderate", 186.00),
       ("97110", "Therapeutic exercise, 15 min", 42.00), ("97140", "Manual therapy, 15 min", 39.00),
       ("72148", "MRI lumbar spine w/o contrast", 1240.00), ("73562", "X-ray knee, 3 views", 96.00),
       ("99284", "Emergency dept visit, moderate-high", 610.00), ("36415", "Venipuncture", 18.00),
       ("80053", "Comprehensive metabolic panel", 44.00), ("J1885", "Ketorolac injection", 22.00)]
MEDS = ["Lisinopril 20 mg daily", "Atorvastatin 40 mg nightly", "Metformin 500 mg twice daily", "Gabapentin 300 mg three times daily",
        "Naproxen 500 mg twice daily as needed", "Cyclobenzaprine 5 mg at bedtime as needed", "Omeprazole 20 mg daily",
        "Duloxetine 30 mg daily", "Acetaminophen 500 mg as needed", "Vitamin D3 2000 IU daily", "Meloxicam 15 mg daily",
        "Tramadol 50 mg every 6 hours as needed (short course)"]


def fmt(d) -> str:
    return d.strftime("%m/%d/%Y")


def fax_cover(rng: random.Random, sender: str, d, pages: int):
    return [("title", "FAX COVER SHEET"),
            ("kv", [("Date", fmt(d)), ("To", "State Disability Determination Services (fictional)"), ("From", sender),
                    ("Pages (including cover)", str(pages)), ("Re", "Medical records request - authorization on file")]),
            ("p", "CONFIDENTIALITY NOTICE: The documents accompanying this facsimile contain confidential health "
                  "information that is legally privileged. This information is intended only for the use of the individual "
                  "or entity named above. If you are not the intended recipient, you are hereby notified that any "
                  "disclosure, copying, distribution, or action taken in reliance on the contents of these documents is "
                  "strictly prohibited. If you have received this fax in error, please notify the sender immediately."),
            ("p", rng.choice(["Records enclosed per your request.", "Please see attached records.", "Partial records; additional to follow.",
                              "Records for the requested date range are enclosed."]))]


CPT_BY_KIND = {"pcp": ["99213", "99214", "36415", "80053"], "ortho": ["99213", "99214", "J1885"], "pt": ["97110", "97140"],
               "er": ["99284", "J1885", "36415"], "imaging": ["RAD"], "pain": ["99214", "J1885"], "neuro": ["99214"], "ce": ["99214"]}
_RAD = ("76499", "Radiology professional interpretation fee", 145.00)


def billing(rng: random.Random, provider: str, d, kind: str = "pcp"):
    codes = CPT_BY_KIND.get(kind, ["99213"])
    pool = [c for c in CPT if c[0] in codes] or [_RAD]
    items = rng.sample(pool, min(len(pool), rng.randint(1, 3)))
    rows = [(f"{fmt(d)}  {c}", f"{desc}  ${amt:,.2f}") for c, desc, amt in items]
    total = sum(a for *_, a in items)
    paid = round(total * rng.uniform(0.55, 0.9), 2)
    return [("title", "Billing Statement - Statement of Account"),
            ("kv", [("Provider", provider), ("Statement date", fmt(d)), ("Account #", f"SYN-{rng.randint(100000, 999999)}")]),
            ("h", "Itemized charges")] + [("kv", rows)] + [
            ("kv", [("Total charges", f"${total:,.2f}"), ("Insurance payments", f"-${paid:,.2f}"),
                    ("Amount due", f"${total - paid:,.2f}")]),
            ("small", "Please remit payment within 30 days. Questions about your bill? Call our billing office Monday-Friday.")]


def reminder(rng: random.Random, provider: str, d):
    return [("title", "Appointment Reminder"),
            ("p", f"This is a reminder of your upcoming appointment on {fmt(d)} at {rng.choice(['8:15', '9:30', '10:45', '1:20', '2:40', '3:50'])} "
                  f"{rng.choice(['AM', 'PM'])} with {provider}."),
            ("p", "Please arrive 15 minutes early and bring your insurance card, a photo ID, and a list of your current "
                  "medications. If you need to cancel or reschedule, please call at least 24 hours in advance. Missed "
                  "appointments without notice may be subject to a fee."),
            ("small", "This is an automated notice. Please do not reply.")]


PRIVACY = ("This notice describes how medical information about you may be used and disclosed and how you can get access "
           "to this information. Please review it carefully. We are required by law to maintain the privacy of protected "
           "health information, to provide individuals with notice of our legal duties and privacy practices, and to "
           "notify affected individuals following a breach of unsecured protected health information. We may use and "
           "disclose your health information for treatment, payment, and health care operations. Other uses and "
           "disclosures will be made only with your written authorization, which you may revoke at any time. You have the "
           "right to inspect and copy your records, to request amendments, to request an accounting of disclosures, to "
           "request restrictions, and to request confidential communications.")


def privacy_notice(provider: str):
    return [("title", "Notice of Privacy Practices"), ("p", provider), ("p", PRIVACY), ("p", PRIVACY),
            ("small", "Acknowledgment of receipt is kept on file.")]


def records_certification(provider: str, d, n_pages: int):
    return [("title", "Certification of Records - Custodian Statement"),
            ("p", f"I certify that the attached {n_pages} pages are true and complete copies of the medical records "
                  f"maintained by {provider} for the patient named above, prepared in the ordinary course of business "
                  "at or near the time of the events recorded."),
            ("kv", [("Custodian of records", "Health Information Management (fictional)"), ("Date", fmt(d))])]


def medication_list(rng: random.Random, provider: str, d, extra: list[str] = ()):
    meds = rng.sample(MEDS[:3] + MEDS[6:7] + MEDS[9:10], 3) + list(extra)
    return [("title", "Medication List"), ("kv", [("Reviewed", fmt(d)), ("Source", provider)]),
            ("h", "Current medications")] + [("p", f"- {m}") for m in meds] + [
            ("h", "Allergies"), ("p", rng.choice(["No known drug allergies.", "Penicillin (rash).", "Sulfa (hives)."]))]


def pharmacy_fills(rng: random.Random, pharmacy: str, start, months: int, meds: list[str]):
    rows = []
    d = start
    for _ in range(months):
        for m in rng.sample(meds, min(len(meds), rng.randint(2, 4))):
            rows.append((fmt(d), f"{m} - qty {rng.choice([30, 60, 90])} - refill"))
        d = d.replace(day=min(d.day, 28))
        d = (d.replace(month=d.month % 12 + 1, year=d.year + (d.month == 12)))
    return [("title", "Pharmacy Fill History"), ("kv", [("Pharmacy", pharmacy)]), ("kv", rows[:22])]


def vitals_visit(rng: random.Random, provider: str, nurse: str, d, reason: str):
    bp = f"{rng.randint(124, 148)}/{rng.randint(76, 92)}"
    return visit(fmt(d), nurse, "Nurse Visit", reason,
                 f"Patient presents for {reason.lower()}. No new complaints reported today.",
                 f"BP {bp}, HR {rng.randint(64, 88)}, Temp 98.{rng.randint(1, 8)} F, Wt {rng.randint(196, 214)} lb. Patient in no acute distress.",
                 "Vitals recorded. " + rng.choice(["Blood pressure near goal.", "Blood pressure slightly above goal.", "Stable."]),
                 rng.choice(["Continue current medications.", "Recheck in 3 months.", "Forward to provider for review."]),
                 vitals=f"BP {bp}") + [("small", f"Supervising provider: {provider}")]


def pt_daily(rng: random.Random, therapist: str, d, n: int, state: str):
    ex = rng.sample(["bridges 2x10", "clamshells 2x12", "prone press-ups 2x10", "nerve glides 2x10", "seated marching 2x15",
                     "quad sets 3x10", "heel slides 2x10", "standing balance 3x30s", "stationary bike 8 min",
                     "sit-to-stand 2x8", "step-ups 2x8", "hamstring stretch 3x30s"], 5)
    return [("title", f"Physical Therapy Daily Note - Visit {n}"),
            ("kv", [("Date of service", fmt(d)), ("Therapist", therapist), ("Pain (0-10)", f"{rng.randint(4, 8)} pre / {rng.randint(3, 7)} post")]),
            ("h", "Interventions"), ("p", "; ".join(ex) + ". Manual therapy 10 minutes. Moist heat 10 minutes."),
            ("h", "Response"), ("p", state),
            ("h", "Plan"), ("p", rng.choice(["Continue plan of care.", "Progress exercises as tolerated.", "Continue home exercise program."]))]


def lab(rng: random.Random, provider: str, d):
    return [("title", "Laboratory Results"), ("kv", [("Collected", fmt(d)), ("Ordering provider", provider)]),
            ("kv", [("Sodium", f"{rng.randint(137, 143)} mmol/L (135-145)"), ("Potassium", f"4.{rng.randint(0, 6)} mmol/L (3.5-5.1)"),
                    ("Creatinine", f"0.{rng.randint(8, 9)}{rng.randint(0, 9)} mg/dL (0.7-1.3)"), ("Glucose", f"{rng.randint(96, 138)} mg/dL"),
                    ("Hemoglobin A1c", f"{rng.randint(6, 7)}.{rng.randint(0, 9)}%"), ("WBC", f"{rng.randint(5, 9)}.{rng.randint(0, 9)} K/uL")]),
            ("small", "Results reviewed. No critical values.")]


def fax_banner_page(page_blocks, sender: str, d, n: int, total: int):
    """A re-faxed copy of a record: same content with a fax transmission banner on top."""
    banner = ("small", f"FAX RECEIVED {fmt(d)} {random.Random(n).randint(8, 17)}:{random.Random(n * 3).randint(10, 59)} "
                       f"FROM: {sender}  P. {n}/{total}")
    return [banner] + list(page_blocks)
