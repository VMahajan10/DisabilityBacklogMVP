"""Story specs for the large synthetic claim files (fictional people, providers, and events).

Each spec defines providers, a clinical storyline by phase, cadence of LLM-written notes, hand-written
KEY pages (the decisive evidence, placed deep in the file) and CONFLICT pages, duplicates, scanned pages,
and the expected outcomes used by the eval.
"""
from datetime import date

from cases_def import imaging, visit


def d(s: str) -> date:
    return date.fromisoformat(s)


def f(x: date) -> str:
    return x.strftime("%m/%d/%Y")


# ============================================================================ CASE 07: medium (~150 pages)
def case07():
    P = {
        "pcp": {"facility": "Cedar Hollow Family Practice (fictional)", "address": "21 Sample Ln, Millbrook, ZZ 00000",
                "clinician": "Lionel P. Varga, MD (Family Medicine)", "nurse": "Tess A. Morrow, RN", "kind": "pcp"},
        "ortho": {"facility": "Northgate Spine & Orthopedics (fictional)", "address": "400 Example Rd, Millbrook, ZZ 00000",
                  "clinician": "Imogen T. Faraday, MD (Orthopedic Spine)", "kind": "ortho"},
        "pt": {"facility": "Brookside Physical Therapy (fictional)", "address": "77 Mock St, Millbrook, ZZ 00000",
               "clinician": "Calvin J. Osei, PT, DPT", "kind": "pt"},
        "er": {"facility": "St. Aldric Community Hospital Emergency Department (fictional)", "address": "1 Hospital Dr, Millbrook, ZZ 00000",
               "clinician": "Rafaela M. Quint, MD (Emergency Medicine)", "kind": "er"},
        "img": {"facility": "Clearview Imaging Center (fictional)", "address": "9 Placeholder Pkwy, Millbrook, ZZ 00000",
                "clinician": "Bertrand O. Kell, MD (Radiology)", "kind": "imaging"},
        "rx": {"facility": "MainStreet Pharmacy #0412 (fictional)", "address": "50 Main St, Millbrook, ZZ 00000", "kind": "pharmacy"},
    }
    ortho = P["ortho"]["clinician"]
    key = {
        "K1_mri": ("img", d("2025-04-02"), imaging(
            "04/02/2025", "MRI Lumbar Spine without contrast", "Left leg radiating pain and weakness after lifting injury",
            "Multiplanar, multisequence MRI of the lumbar spine without contrast.",
            "L4-L5: Large left paracentral disc extrusion measuring 10 mm, migrating inferiorly behind the L5 body, with "
            "severe compression and posterior displacement of the traversing left L5 nerve root. Moderate left lateral "
            "recess stenosis. L5-S1: Mild disc bulge without nerve root compression. Conus normal.",
            "Large left paracentral L4-L5 disc extrusion with severe compression of the traversing left L5 nerve root.",
            P["img"]["clinician"], "XR lumbar spine 01/24/2025.")),
        "K2_walker": ("ortho", d("2025-07-15"), visit(
            "07/15/2025", ortho, "Spine Follow-up", "Worsening left leg weakness and falls",
            "Symptoms have worsened despite physical therapy and medications. Reports three falls in the past month "
            "when the left leg gave way. Radiating pain from the left buttock to the dorsum of the left foot with numbness "
            "over the great toe. Cannot walk more than 50 feet.",
            "Positive straight leg raise on the left at 30 degrees in both sitting and supine positions. Decreased "
            "sensation to light touch and pinprick in the left L5 dermatome. Left extensor hallucis longus 3+/5 and left "
            "ankle dorsiflexion 4-/5. Left foot slap with gait. Unable to heel walk on the left.",
            "Left L5 radiculopathy due to L4-L5 disc extrusion (MRI 04/02/2025) with progressive motor deficit and falls.",
            "Prescribed a front-wheeled walker. Patient has a documented medical need for a walker for all ambulation "
            "because of left leg weakness and falls; a single cane was tried and is unsafe. Need expected to last at "
            "least 12 months. Neurosurgery referral placed.")),
        "K3_mss": ("ortho", d("2026-07-20"), [
            ("title", "Treating Source Medical Source Statement (Physical) - 07/20/2026"),
            ("kv", [("Treating source", ortho), ("Treating since", "02/11/2025")]),
            ("h", "Assistive device"),
            ("p", "The patient requires a front-wheeled walker for all ambulation and has required it continuously since "
                  "07/15/2025. Without it the patient falls. This need is expected to continue for at least another 12 months."),
            ("h", "Functional capacity"),
            ("p", "Stand and walk less than 2 hours total in an 8-hour day, no more than 10 minutes at a time. Lift less "
                  "than 10 pounds occasionally. Both hands are needed on the walker while walking.")]),
    }
    conflict = {
        "C1_pt_improved": ("pt", d("2025-06-10"), [
            ("title", "Physical Therapy Progress Report - 06/10/2025"),
            ("kv", [("Therapist", P["pt"]["clinician"]), ("Visits completed", "12")]),
            ("p", "The patient reports pain improved by about 50 percent since starting therapy. Walking tolerance has "
                  "improved to 20 minutes on level ground without an assistive device. Straight leg raise is less "
                  "provocative. Good progress toward goals."),
            ("h", "Plan"), ("p", "Continue twice weekly for 4 more weeks.")]),
    }
    return {
        "case_id": "case07_medium_lumbar", "target_pages": 150, "seed": 7,
        "title": "Medium (~150 pages): lumbar nerve root compromise, key evidence mid-file",
        "claimant": {"name": "Delphine R. Achterberg-Moss", "dob": "1969-05-19", "alleged_onset_date": "2025-01-20",
                     "filed_date": "2026-09-10", "claim_number": "SYN-26-000107"},
        "span": (d("2023-06-01"), d("2026-08-20")), "providers": P,
        "storyline": [
            (d("2023-06-01"), d("2025-01-19"), "Chronic hypertension and prediabetes. Occasional mild low back stiffness, no leg symptoms, normal neuro exam."),
            (d("2025-01-20"), d("2025-07-14"), "Lifting injury 01/20/2025 with new left leg radiating pain to the foot, numbness, mild left foot weakness. Conservative care: NSAIDs, gabapentin, physical therapy."),
            (d("2025-07-15"), d("2026-08-20"), "Persistent left L5 radiculopathy with weakness and falls. Uses a front-wheeled walker. Awaiting neurosurgery. Chronic pain limits standing and walking."),
        ],
        "cadence": {"pcp": 90, "ortho": 75, "er_visits": 2, "pt_episodes": [(d("2025-03-01"), 14)]},
        "doc_order": ["pcp", "er", "rx", "img", "ortho", "pt", "fax", "claimant"],
        "padding_weights": {"pcp": 3, "ortho": 1, "pt": 2, "er": 1, "img": 1, "rx": 1},
        "key": key, "conflict": conflict,
        "fax_copies": {"sender": "Northgate Spine & Orthopedics (fictional)", "from_providers": ["ortho", "img"], "n": 10,
                       "include": ["K1_mri"]},
        "scan_fraction": 0.04, "force_scan": [],
        "expected": {"listing_outcome": ["criteria_appear_met"], "listings": ["1.15"], "triage": "fast_track", "cal": False,
                     "missing_flags": [],
                     "expected_conflicts": [{"topic": "symptom trend / walking ability", "refs": ["C1_pt_improved", "K2_walker"]}]},
    }


# ============================================================================ CASE 08: large (~500 pages)
def case08():
    P = {
        "pcp": {"facility": "Willowbend Primary Care (fictional)", "address": "8 Example Ave, Fairhaven, ZZ 00000",
                "clinician": "Harriet N. Obuya, MD (Internal Medicine)", "nurse": "Gus L. Pell, LPN", "kind": "pcp"},
        "ortho": {"facility": "Fairhaven Joint & Sports Clinic (fictional)", "address": "120 Mock Blvd, Fairhaven, ZZ 00000",
                  "clinician": "Desmond K. Albrecht, MD (Orthopedic Surgery)", "kind": "ortho"},
        "pt": {"facility": "Harborline Rehabilitation (fictional)", "address": "33 Sample Wharf, Fairhaven, ZZ 00000",
               "clinician": "Mira S. Kowal, PT, DPT", "kind": "pt"},
        "er": {"facility": "Fairhaven General Hospital Emergency Department (fictional)", "address": "2 Hospital Way, Fairhaven, ZZ 00000",
               "clinician": "Theo V. Marchand, MD (Emergency Medicine)", "kind": "er"},
        "uc": {"facility": "QuickCare Urgent Care - Fairhaven (fictional)", "address": "70 Retail Row, Fairhaven, ZZ 00000",
               "clinician": "Lena J. Strand, PA-C", "kind": "er"},
        "img": {"facility": "Fairhaven Radiology Associates (fictional)", "address": "15 Imaging Ct, Fairhaven, ZZ 00000",
                "clinician": "Oskar P. Lindahl, MD (Radiology)", "kind": "imaging"},
        "rx": {"facility": "Harbor Drug #221 (fictional)", "address": "90 Main St, Fairhaven, ZZ 00000", "kind": "pharmacy"},
        "ce": {"facility": "Coastal Disability Evaluations LLC (fictional)", "address": "400 Exam Plaza, Fairhaven, ZZ 00000",
               "clinician": "Rowena B. Thackeray, MD (Consultative Examiner)", "kind": "ce"},
    }
    ortho = P["ortho"]["clinician"]
    key = {
        "K1_xray": ("img", d("2025-10-03"), imaging(
            "10/03/2025", "XR Bilateral Knees, weight-bearing, 4 views", "Progressive bilateral knee pain, falls",
            "Standing AP, lateral, and sunrise views of both knees.",
            "Right knee: complete loss of medial joint space with bone-on-bone apposition, large osteophytes, subchondral "
            "sclerosis and cysts, varus deformity. Left knee: severe medial joint space narrowing with osteophytes.",
            "Severe tricompartmental-predominant medial osteoarthritis of the right knee (end-stage) and severe medial "
            "osteoarthritis of the left knee.", P["img"]["clinician"], "XR bilateral knees 03/15/2024.")),
        "K2_canes": ("ortho", d("2026-02-18"), visit(
            "02/18/2026", ortho, "Orthopedic Follow-up", "Bilateral knee pain, worsening, falls",
            "Knee pain has worsened substantially since last fall. Two falls at home in January when the right knee "
            "buckled. Cannot walk more than half a block. No longer able to manage stairs.",
            "Antalgic gait with bilateral knee instability. Right knee ROM 10 to 85 degrees with flexion contracture; left "
            "knee 5 to 95 degrees. Bilateral effusions. Quadriceps 4/5 bilaterally.",
            "End-stage right knee and severe left knee osteoarthritis (XR 10/03/2025), worsening, with falls.",
            "Prescribed bilateral canes. The patient has a documented medical need for bilateral canes for all "
            "ambulation outside the home because of bilateral knee instability; expected to last at least 12 months or "
            "until arthroplasty.")),
        "K3_ce": ("ce", d("2026-06-30"), [
            ("title", "Consultative Examination - Musculoskeletal Findings and Opinion - 06/30/2026"),
            ("kv", [("Examiner", P["ce"]["clinician"]), ("Records reviewed", "None provided prior to exam")]),
            ("p", "The claimant walked approximately 60 feet from the waiting room carrying two canes in one hand without "
                  "using them. Gait mildly antalgic but steady without an assistive device. Right knee ROM 5 to 100 degrees, "
                  "left 0 to 115 degrees. No effusion today. Quadriceps 5-/5 bilaterally."),
            ("h", "Opinion"),
            ("p", "An assistive device is not medically necessary for ambulation over short distances on level surfaces. "
                  "Could stand and walk about 4 hours in an 8-hour workday.")]),
    }
    conflict = {
        "C1_pt_improved": ("pt", d("2025-08-20"), [
            ("title", "Physical Therapy Discharge Summary - 08/20/2025"),
            ("kv", [("Therapist", P["pt"]["clinician"]), ("Visits completed", "18 of 18")]),
            ("p", "Significant improvement. The patient now ambulates community distances without an assistive device and "
                  "is independent with stairs using one handrail. Knee pain reduced to 3/10. All goals met."),
            ("h", "Plan"), ("p", "Discharged to independent home exercise program.")]),
    }
    return {
        "case_id": "case08_large_knee_conflict", "target_pages": 500, "seed": 8,
        "title": "Large (~500 pages): bilateral knee OA, improved-then-worse and treating vs CE conflicts",
        "claimant": {"name": "Augustin F. Pellegrino-Rhee", "dob": "1964-10-02", "alleged_onset_date": "2025-02-01",
                     "filed_date": "2026-08-05", "claim_number": "SYN-26-000108"},
        "span": (d("2022-11-01"), d("2026-07-25")), "providers": P,
        "storyline": [
            (d("2022-11-01"), d("2025-01-31"), "Type 2 diabetes and hypertension. Intermittent bilateral knee aches managed with acetaminophen; full function."),
            (d("2025-02-01"), d("2025-08-31"), "Progressive bilateral knee pain, right worse, with swelling and stiffness. Injections and physical therapy."),
            (d("2025-09-01"), d("2026-07-25"), "Worsening knee pain with instability, falls, reduced walking distance. Uses canes. Weight-loss program before planned right knee arthroplasty."),
        ],
        "cadence": {"pcp": 75, "ortho": 60, "er_visits": 4, "uc_visits": 3,
                    "pt_episodes": [(d("2024-05-01"), 10), (d("2025-05-10"), 18), (d("2026-04-01"), 12)]},
        "doc_order": ["pcp", "rx", "uc", "er", "img", "pt", "ortho", "fax", "ce", "claimant"],
        "padding_weights": {"pcp": 4, "ortho": 2, "pt": 3, "er": 1, "uc": 1, "img": 1, "rx": 2},
        "key": key, "conflict": conflict,
        "fax_copies": {"sender": "Fairhaven Joint & Sports Clinic (fictional)", "from_providers": ["ortho", "img", "pt"], "n": 40,
                       "include": ["K1_xray"]},
        "scan_fraction": 0.04, "force_scan": [],
        "expected": {"listing_outcome": ["insufficient_evidence"], "listings": ["1.18"], "triage": "senior_examiner", "cal": False,
                     "missing_flags": [],
                     "expected_conflicts": [{"topic": "walking / assistive device (PT improved vs ortho worse)", "refs": ["C1_pt_improved", "K2_canes"]},
                                            {"topic": "assistive device need (treating vs CE)", "refs": ["K3_ce", "K2_canes"]}]},
    }


# ============================================================================ CASE 09: extra large (~1,500 pages)
def case09():
    P = {
        "pcp": {"facility": "Ridgeview Community Health Center (fictional)", "address": "300 Sample St, Eastvale, ZZ 00000",
                "clinician": "Corinne A. Bledsoe, DO (Family Medicine)", "nurse": "Pia R. Gant, RN", "kind": "pcp"},
        "ortho": {"facility": "Eastvale Orthopedic Spine Institute (fictional)", "address": "55 Spine Way, Eastvale, ZZ 00000",
                  "clinician": "Marcus J. Ferreira-Holt, MD (Orthopedic Spine)", "kind": "ortho"},
        "pain": {"facility": "Eastvale Interventional Pain Clinic (fictional)", "address": "56 Spine Way, Eastvale, ZZ 00000",
                 "clinician": "Sunniva K. Albright, MD (Pain Medicine)", "kind": "pain"},
        "pt": {"facility": "Summit Rehab & Wellness (fictional)", "address": "12 Mock Ave, Eastvale, ZZ 00000",
               "clinician": "Dorian F. Wexley, PT, DPT", "kind": "pt"},
        "er": {"facility": "Eastvale Regional Medical Center Emergency Department (fictional)", "address": "1 Medical Center Dr, Eastvale, ZZ 00000",
               "clinician": "Noor E. Halvorsen, MD (Emergency Medicine)", "kind": "er"},
        "uc": {"facility": "FirstStop Urgent Care - Eastvale (fictional)", "address": "88 Retail Pkwy, Eastvale, ZZ 00000",
               "clinician": "Jasper Q. Lund, PA-C", "kind": "er"},
        "img": {"facility": "Eastvale Diagnostic Imaging (fictional)", "address": "40 Scan Rd, Eastvale, ZZ 00000",
                "clinician": "Henrietta W. Okoro, MD (Radiology)", "kind": "imaging"},
        "neuro": {"facility": "Valley Neurology Associates (fictional)", "address": "9 Neuron Ct, Eastvale, ZZ 00000",
                  "clinician": "Ilya M. Sorensen, MD (Neurology)", "kind": "neuro"},
        "rx": {"facility": "CareRite Pharmacy #1187 (fictional)", "address": "200 Main St, Eastvale, ZZ 00000", "kind": "pharmacy"},
    }
    ortho = P["ortho"]["clinician"]
    key = {
        "K1_mri": ("img", d("2025-05-14"), imaging(
            "05/14/2025", "MRI Lumbar Spine without contrast", "Right leg radiculopathy, progressive weakness",
            "Multiplanar, multisequence MRI of the lumbar spine without contrast.",
            "L5-S1: Right paracentral disc extrusion measuring 11 mm with inferior migration, severely compressing the "
            "traversing right S1 nerve root. L4-L5: Moderate broad-based disc bulge with mild right foraminal narrowing. "
            "No fracture. Conus normal.",
            "Right paracentral L5-S1 disc extrusion with severe compression of the traversing right S1 nerve root.",
            P["img"]["clinician"], "MRI lumbar spine 02/08/2023.")),
        "K2_walker": ("ortho", d("2025-09-03"), visit(
            "09/03/2025", ortho, "Spine Follow-up", "Worsening right leg weakness, falls",
            "Right leg pain radiating to the lateral foot has worsened despite epidural injections, therapy, and "
            "medications. Four falls since July when the right leg buckled. Walks less than 50 feet.",
            "Positive straight leg raise on the right at 25 degrees seated and supine. Decreased sensation to pinprick "
            "along the right S1 dermatome (lateral foot). Right plantar flexion 3+/5, right ankle reflex absent. Unable "
            "to toe walk on the right.",
            "Right S1 radiculopathy from L5-S1 disc extrusion (MRI 05/14/2025) with progressive weakness and falls.",
            "Prescribed a front-wheeled walker. The patient has a documented medical need for a walker for all "
            "ambulation due to right leg weakness and falls; need expected to last at least 12 months. Surgical "
            "consultation pending cardiology clearance.")),
        "K3_mss": ("ortho", d("2026-08-12"), [
            ("title", "Treating Source Medical Source Statement (Physical) - 08/12/2026"),
            ("kv", [("Treating source", ortho), ("Treating since", "12/02/2024")]),
            ("h", "Assistive device"),
            ("p", "The patient requires a front-wheeled walker for all ambulation and has needed it continuously since "
                  "09/03/2025. The need is expected to continue for at least 12 more months."),
            ("h", "Functional capacity"),
            ("p", "Stand/walk under 2 hours in an 8-hour day. Sit 4 hours with position changes. Lift under 10 pounds.")]),
    }
    conflict = {
        "C1_esi_improved": ("pain", d("2025-03-10"), visit(
            "03/10/2025", P["pain"]["clinician"], "Post-procedure Follow-up", "Follow-up after epidural steroid injection",
            "Reports about 70 percent improvement in right leg pain since the right L5-S1 transforaminal epidural steroid "
            "injection on 02/17/2025. Now walking up to 1 mile with the dog without difficulty.",
            "Gait normal. Straight leg raise negative bilaterally today. Strength 5/5 in the lower extremities.",
            "Right lumbar radiculopathy, markedly improved after injection.",
            "No further injections planned at this time. Return as needed.")),
    }
    return {
        "case_id": "case09_xl_lumbar_ocr", "target_pages": 1500, "seed": 9,
        "title": "Extra large (~1,500 pages): lumbar S1 compromise, key MRI only on a scanned page",
        "claimant": {"name": "Winslow T. Abernathy-Quade", "dob": "1967-01-28", "alleged_onset_date": "2024-11-05",
                     "filed_date": "2026-09-20", "claim_number": "SYN-26-000109"},
        "span": (d("2022-09-01"), d("2026-08-30")), "providers": P,
        "storyline": [
            (d("2022-09-01"), d("2024-11-04"), "Hypertension, hyperlipidemia, obesity. Intermittent mechanical low back pain with normal neuro exam; working as a delivery driver."),
            (d("2024-11-05"), d("2025-06-30"), "Onset 11/05/2024 of right leg radiating pain to the lateral foot after lifting. Epidural injections, gabapentin, physical therapy; fluctuating course."),
            (d("2025-07-01"), d("2026-08-30"), "Progressive right S1 radiculopathy with weakness, falls, and walker use. Chronic pain, poor sleep, depressed mood. Surgery delayed for cardiac clearance."),
        ],
        "cadence": {"pcp": 45, "ortho": 50, "pain": 60, "neuro": 240, "er_visits": 7, "uc_visits": 6,
                    "pt_episodes": [(d("2023-04-01"), 12), (d("2025-01-06"), 20), (d("2025-10-01"), 16), (d("2026-03-02"), 16)]},
        "doc_order": ["pcp", "rx", "uc", "er", "img", "pain", "ortho", "pt", "neuro", "fax", "claimant"],
        "padding_weights": {"pcp": 6, "ortho": 2, "pt": 4, "pain": 2, "er": 2, "uc": 1, "img": 1, "neuro": 1, "rx": 3},
        "key": key, "conflict": conflict,
        "fax_copies": {"sender": "Eastvale Orthopedic Spine Institute (fictional)", "from_providers": ["ortho", "pain", "pt", "er"],
                       "n": 120, "include": ["K2_walker"]},
        "scan_fraction": 0.04, "force_scan": ["K1_mri"],
        "expected": {"listing_outcome": ["criteria_appear_met"], "listings": ["1.15"], "triage": "fast_track", "cal": False,
                     "missing_flags": [],
                     "expected_conflicts": [{"topic": "symptom trend / walking ability (improved after ESI vs worse)",
                                             "refs": ["C1_esi_improved", "K2_walker"]}]},
    }


LARGE_CASES = [case07, case08, case09]
