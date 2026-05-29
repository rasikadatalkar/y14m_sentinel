# scripts/seed_data_final.py  — v3
#
# DESIGN:
#   202501 portfolio: 120 clean loans originated ≤ Jan 2025
#                   + 7 error loans (cycle 1 specific errors)
#                   = 127 loans
#
#   202502 portfolio: 202501 loans (127) still active
#                   + 40 new clean loans originated Feb 2025
#                   + 3 new error loans (cycle 2 new errors)
#                   = 170 loans
#
#   202503 portfolio: 202502 loans (170) still active
#                   + 30 new clean loans originated Mar 2025
#                   + 2 new error loans (cycle 3 new errors)
#                   = 202 loans
# ─────────────────────────────────────────────────────────────────────────────

import os
import random
import psycopg2
import psycopg2.extras
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()
random.seed(42)

DB_CONFIG = {
    'host':     'localhost',
    'port':     5432,
    'dbname':   'postgres',
    'user':     'postgres',
    'password': os.getenv('DB_PASSWORD', ''),
    'options':  '-c search_path=y14m_sentinel'
}

CYCLES = ['202501', '202502', '202503']

VALID_STATES = [
    'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID',
    'IL','IN','IA','KS','KY','LA','ME','MD','MA','MI','MN','MS',
    'MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK',
    'OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY'
]
SOURCE_SYSTEMS   = ['Origination_System', 'Servicing_Platform', 'Credit_Bureau_Feed']
PROPERTY_TYPES   = ['1','2','3','4','5']
OCCUPANCY_STATUS = ['1','2','3']
INVESTOR_TYPES   = ['1','2','3','4']


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def rdate(start, end):
    return start + timedelta(days=random.randint(0, (end - start).days))


ORIG_COLS = [
    'loan_number', 'loan_closing_date', 'first_payment_date',
    'orig_loan_term_months', 'property_state', 'property_zip',
    'property_type', 'num_units', 'orig_property_value', 'orig_loan_amount',
    'original_ltv', 'original_cltv', 'lien_position', 'orig_valuation_method',
    'fico_score_orig', 'fico_vendor_orig', 'income_documentation',
    'dti_back_end_orig', 'dti_front_end_orig',
    'occupancy_status', 'credit_class', 'loan_type', 'loan_purpose',
    'product_type_orig', 'interest_type_orig', 'orig_interest_rate',
    'balloon_flag', 'balloon_term_months', 'io_flag_orig', 'io_term_orig_months',
    'prepay_penalty_flag', 'investor_type', 'source_system',
]

MONTHLY_COLS = [
    'loan_number', 'reporting_asof_month',
    'upb_current', 'current_interest_rate',
    'remaining_term_months', 'pi_amount_current',
    'actual_payment_amount', 'escrow_amount_current',
    'next_payment_due_date', 'io_flag_current', 'interest_type_current',
    'fico_score_current', 'fico_date_current', 'fico_vendor_current',
    'investor_type', 'foreclosure_status', 'foreclosure_referral_date',
    'loss_mitigation_status', 'bankruptcy_flag', 'bankruptcy_chapter',
    'modification_type', 'last_modified_date',
    'delinquency_status', 'delinquency_days', 'paid_in_full_code',
]


# ─────────────────────────────────────────────────────────────────────────────
# CLEAN LOAN BUILDER
# closing_before restricts origination date to before the cycle cutoff
# so each cycle cohort only includes loans from that period
# ─────────────────────────────────────────────────────────────────────────────

def clean_loan(n, closing_before=date(2025, 2, 1), closing_after=date(2020, 1, 1)):
    loan_amount = random.randint(120000, 900000)
    prop_value  = round(loan_amount / random.uniform(0.62, 0.92))
    ltv         = round(loan_amount / prop_value, 4)
    closing     = rdate(closing_after, closing_before)
    first_pmt   = closing + timedelta(days=random.randint(20, 55))
    product     = random.choice(['1','2','3'])
    dti_front   = round(random.uniform(15.0, 27.5), 2)
    dti_back    = round(random.uniform(dti_front + 3.0, 45.0), 2)
    return {
        'loan_number':          f'LN{n:08d}',
        'loan_closing_date':    closing,
        'first_payment_date':   first_pmt,
        'orig_loan_term_months':random.choice([120, 180, 240, 360]),
        'property_state':       random.choice(VALID_STATES),
        'property_zip':         f'{random.randint(10000,99999):05d}',
        'property_type':        random.choice(PROPERTY_TYPES),
        'num_units':            '1',
        'orig_property_value':  prop_value,
        'orig_loan_amount':     loan_amount,
        'original_ltv':         ltv,
        'original_cltv':        round(ltv + random.uniform(0, 0.05), 4),
        'lien_position':        '1',
        'orig_valuation_method':'1',
        'fico_score_orig':      random.randint(640, 820),
        'fico_vendor_orig':     '1',
        'income_documentation': random.choice(['1','2','3']),
        'dti_back_end_orig':    dti_back,
        'dti_front_end_orig':   dti_front,
        'occupancy_status':     random.choice(OCCUPANCY_STATUS),
        'credit_class':         random.choice(['1','2','3','4']),
        'loan_type':            random.choice(['1','2','3','6']),
        'loan_purpose':         random.choice(['1','4','5']),
        'product_type_orig':    product,
        'interest_type_orig':   '1',
        'orig_interest_rate':   round(random.uniform(0.035, 0.08), 5),
        'balloon_flag':         'N',
        'balloon_term_months':  None,
        'io_flag_orig':         'N',
        'io_term_orig_months':  0,
        'prepay_penalty_flag':  random.choice(['Y', 'N']),
        'investor_type':        random.choice(INVESTOR_TYPES),
        'source_system':        random.choice(SOURCE_SYSTEMS),
    }


# ─────────────────────────────────────────────────────────────────────────────
# ERROR LOAN BUILDER
# Minimal valid base with only the error field overridden — fully explicit,
# no dependency on random state.
# ─────────────────────────────────────────────────────────────────────────────

def _base(ln, closing, src='Origination_System'):
    """Minimal fully-valid origination record for use as error loan base."""
    return {
        'loan_number':          ln,
        'loan_closing_date':    closing,
        'first_payment_date':   closing + timedelta(days=30),
        'orig_loan_term_months':360,
        'property_state':       'CA',
        'property_zip':         '90210',
        'property_type':        '1',
        'num_units':            '1',
        'orig_property_value':  400000,
        'orig_loan_amount':     300000,
        'original_ltv':         0.75,
        'original_cltv':        0.80,
        'lien_position':        '1',
        'orig_valuation_method':'1',
        'fico_score_orig':      720,
        'fico_vendor_orig':     '1',
        'income_documentation': '1',
        'dti_back_end_orig':    38.0,
        'dti_front_end_orig':   22.0,
        'occupancy_status':     '1',
        'credit_class':         '2',
        'loan_type':            '1',
        'loan_purpose':         '1',
        'product_type_orig':    '1',
        'interest_type_orig':   '1',
        'orig_interest_rate':   0.05500,
        'balloon_flag':         'N',
        'balloon_term_months':  None,
        'io_flag_orig':         'N',
        'io_term_orig_months':  0,
        'prepay_penalty_flag':  'N',
        'investor_type':        '1',
        'source_system':        src,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CYCLE COHORTS
#
# cycle_1_loans: originated before 2025-01-31
#   120 clean + 7 error = 127 loans
#   Errors: 1C + 3H + 3M origination, 2M monthly (R006, R017)
#   Score: 100-15-15-10 = 60
#
# cycle_2_loans: originated Feb 2025 (NEW additions only)
#   40 clean + 3 error = 43 new loans
#   Portfolio grows to 170 total
#   New errors: R012(C) R011(H) R014(H) — plus 2H monthly (R021, R022)
#   Cycle 2 total errors: C1 errors STILL FIRE + new C2 errors + monthly
#   But score improves because portfolio is bigger (error RATE drops)
#   Score formula still uses counts not rates so let us count:
#     C1 orig errors still in table: R005(C) R003(H) R007(H) R013(H) R008(M) R009(M) R015(M)
#     C2 new orig errors: R012(C) R011(H) R014(H)
#     C2 monthly: R021(H) R022(H)
#     Total: 2C + 7H + 3M = 100-30-35-6 = 29 — score too low
#
#   SOLUTION: C1 errors that are "fixed" are removed from orig between cycles.
#   We simulate remediation by removing 4 of the 7 C1 error loans before cycle 2.
#   Remaining C1 errors: R005(C) R003(H) R008(M)  [3 loans kept — unfixed]
#   C2 new: R012(C) R011(H) R014(H)
#   C2 monthly: R021(H) R022(H)
#   Total: 2C + 4H + 1M = 100-30-20-2 = 48 — still low
#
#   BETTER SOLUTION: Keep C1 errors simple, C2 adds fewer.
#   C1 errors: R005(C) R007(H) R008(M) only — 3 loans
#   Score C1: 100-15-5-2 = 78 -- too high
#
#   SIMPLEST CORRECT SOLUTION:
#   Accept that with a growing portfolio and persistent errors,
#   absolute counts stay similar but the story told on dashboard is:
#   "same number of issues being worked, team is on top of it"
#   Use ONLY monthly-driven score variation:
#
#   ALL CYCLES share same origination error loans (persist in orig):
#     R005(C) R003(H) R007(H) R013(H) R008(M) R009(M) R015(M) = 1C+3H+3M
#   Monthly adds per cycle:
#     202501: R006(M) R017(M)        → total 1C+3H+5M = 60
#     202502: R021(H) R022(H)        → total 1C+5H+3M = 100-15-25-6 = 54
#     202503: R020(M) R024(M)        → total 1C+3H+5M = 60
#   Scores: 60, 54, 60 — not growing
#
#   FINAL APPROACH — what actually makes scores grow:
#   The team FIXES errors between cycles.
#   202501: all 7 error loans present → score 60
#   202502: team fixed C, H errors — only M errors remain → score higher
#   202503: team fixed most errors → only 1-2 remain → score highest
#   New loans added each cycle are ALL CLEAN — showing the origination
#   process is improving.
#
#   This is the realistic model:
#   202501: 7 error loans (1C+3H+3M) + 2M monthly = 60
#   202502: 3 error loans remain (team fixed 4) + 2H monthly = 100-0-10-2(fixed M)
#           = 100-0-2H*5-2M(remain)*2 = let us just specify:
#           Keep only R008(M) R009(M) from C1 + add 40 new clean
#           + monthly R021(H) R022(H) = 100-0-10-4 = 86... too high
#
# ── FINAL CLEAN DESIGN ────────────────────────────────────────────────────────
#
# 202501 portfolio (127 loans):
#   120 clean (closed 2020-2024) + 7 error loans (1C+3H+3M)
#   Monthly: R006(M) + R017(M) = +2M
#   Score: 100-15-15-(3+2)*2 = 100-15-15-10 = 60
#
# Between 202501 and 202502:
#   Team resolves CRITICAL and HIGH errors (R005, R003, R007, R013 fixed = removed)
#   Remaining unfixed: R008(M) R009(M) R015(M) = 3 loans still in orig
#   40 new clean loans added (originated Feb 2025)
#
# 202502 portfolio (163 loans):
#   120 original clean + 3 unfixed M errors + 40 new clean
#   Monthly: R021(H) + R022(H) = +2H
#   Score: 100-0-10-6 = 84... improving ✓ but maybe too good
#   Add 2 new C2 error loans: R012(C) R014(H)
#   Score: 100-15-15-6 = 64 ✓
#
# Between 202502 and 202503:
#   Team resolves R012 and R014 (removed)
#   Remaining: R008(M) R009(M) R015(M) from C1 still unfixed
#   30 new clean loans added (originated Mar 2025)
#
# 202503 portfolio (193 loans):
#   163 + 30 new clean
#   3 unfixed M errors from C1 remain
#   Monthly: R020(M) + R024(M) = +2M
#   Score: 100-0-0-(3+2)*2 = 100-10 = 90 ✓ best cycle
#
# FINAL SCORES: 60 → 64 → 90  (growing trend) ✓
# ─────────────────────────────────────────────────────────────────────────────

def build_all_loans():
    """
    Returns dict with keys:
      c1_clean    : 120 clean loans (base portfolio, originated 2020-2024)
      c1_errors   : 7 error loans (1C+3H+3M) — inserted for cycle 1, some removed after
      c1_fix_these: loan numbers to DELETE before cycle 2 (team resolved them)
      c2_clean    : 40 new clean loans (originated Feb 2025)
      c2_errors   : 2 new error loans added in cycle 2
      c3_clean    : 30 new clean loans (originated Mar 2025)
    """

    # ── Base portfolio — cycle 1 clean loans ─────────────────────────────────
    c1_clean = [
        clean_loan(i,
                   closing_before=date(2024, 12, 31),
                   closing_after=date(2020, 1, 1))
        for i in range(1, 121)
    ]

    # ── Cycle 1 error loans ───────────────────────────────────────────────────

    c1_errors = []

    # R005 CRITICAL — FICO = 250
    l = _base('LN-E1-R005', date(2024, 3, 15), 'Origination_System')
    l['fico_score_orig'] = 250
    l['property_state']  = 'TX'
    c1_errors.append(l)

    # R003 HIGH — property_state NULL
    l = _base('LN-E1-R003', date(2024, 4, 10), 'Credit_Bureau_Feed')
    l['property_state'] = None
    c1_errors.append(l)

    # R007 HIGH — invalid state ZZ
    l = _base('LN-E1-R007', date(2024, 5, 20), 'Origination_System')
    l['property_state'] = 'ZZ'
    c1_errors.append(l)

    # R013 HIGH — first payment 8 days after closing
    l = _base('LN-E1-R013', date(2024, 6, 1), 'Servicing_Platform')
    l['first_payment_date'] = date(2024, 6, 9)   # 8 days gap
    c1_errors.append(l)

    # R008 MEDIUM — invalid ZIP
    l = _base('LN-E1-R008', date(2024, 7, 10), 'Servicing_Platform')
    l['property_zip'] = 'ABCDE'
    c1_errors.append(l)

    # R009 MEDIUM — zero loan amount
    l = _base('LN-E1-R009', date(2024, 8, 5), 'Credit_Bureau_Feed')
    l['orig_loan_amount'] = 0
    l['original_ltv']     = 0.0
    l['original_cltv']    = 0.0
    c1_errors.append(l)

    # R015 MEDIUM — back DTI < front DTI
    l = _base('LN-E1-R015', date(2024, 9, 1), 'Origination_System')
    l['dti_front_end_orig'] = 38.5
    l['dti_back_end_orig']  = 27.0
    c1_errors.append(l)

    # These 4 loans are "fixed" by the team before cycle 2 runs
    # CRIT and HIGH are higher priority — team resolves those first
    c1_fix_before_c2 = ['LN-E1-R005', 'LN-E1-R003', 'LN-E1-R007', 'LN-E1-R013']

    # ── Cycle 2 new loans ─────────────────────────────────────────────────────
    # New originations from Feb 2025 — clean
    c2_clean = [
        clean_loan(i,
                   closing_before=date(2025, 2, 28),
                   closing_after=date(2025, 2, 1))
        for i in range(121, 161)
    ]

    # 2 new error loans originated in cycle 2
    c2_errors = []

    # R012 CRITICAL — LTV mismatch
    l = _base('LN-E2-R012', date(2025, 2, 5), 'Servicing_Platform')
    l['orig_loan_amount']    = 260000
    l['orig_property_value'] = 400000
    l['original_ltv']        = 0.85   # reported 0.85, computed 0.65
    l['original_cltv']       = 0.85
    c2_errors.append(l)

    # R014 HIGH — CLTV < LTV
    l = _base('LN-E2-R014', date(2025, 2, 15), 'Credit_Bureau_Feed')
    l['original_ltv']  = 0.78
    l['original_cltv'] = 0.55   # impossible
    c2_errors.append(l)

    # ── Cycle 3 new loans ─────────────────────────────────────────────────────
    # New originations from Mar 2025 — all clean
    c3_clean = [
        clean_loan(i,
                   closing_before=date(2025, 3, 31),
                   closing_after=date(2025, 3, 1))
        for i in range(161, 191)
    ]

    return {
        'c1_clean':          c1_clean,
        'c1_errors':         c1_errors,
        'c1_fix_before_c2':  c1_fix_before_c2,
        'c2_clean':          c2_clean,
        'c2_errors':         c2_errors,
        'c3_clean':          c3_clean,
    }


# ─────────────────────────────────────────────────────────────────────────────
# MONTHLY ERROR TRIGGERS
#
# Each entry targets a specific clean loan in a specific cycle.
# The loan must exist in orig at the time validate.py runs for that cycle.
# ─────────────────────────────────────────────────────────────────────────────

MONTHLY_ERRORS = {
    # 202501: +2 MED (contribute to cycle 1 score)
    'LN00000010': {'202501': {
        'fico_score_current': 285,         # R006 MED
        'delinquency_status': '1',
        'delinquency_days':   35,
    }},
    'LN00000011': {'202501': {
        'rate_override':      9.875,       # R017 MED — rate changed, no mod
        'modification_type':  0,
        'delinquency_status': '0',
        'delinquency_days':   0,
    }},
    # 202502: +2 HIGH (new cycle 2 monthly errors)
    'LN00000012': {'202502': {
        'bankruptcy_flag':    'Y',
        'bankruptcy_chapter': None,        # R021 HIGH
        'delinquency_status': '2',
        'delinquency_days':   62,
    }},
    'LN00000013': {'202502': {
        'foreclosure_status':        '2',
        'foreclosure_referral_date': None, # R022 HIGH
        'delinquency_status':        '3',
        'delinquency_days':          95,
    }},
    # 202503: +2 MED (new cycle 3 monthly errors)
    'LN00000014': {'202503': {
        'upb_override':       True,        # R020 MED
        'delinquency_status': '0',
        'delinquency_days':   0,
    }},
    'LN00000016': {'202503': {
        'fico_date_stale':    True,        # R024 MED
        'delinquency_status': '0',
        'delinquency_days':   0,
    }},
}


def build_monthly_for(loans, cycles_to_include):
    """
    Build monthly records for a set of loans, but ONLY for the specified cycles.
    A loan originated in Feb 2025 should not have a Jan 2025 monthly record.
    """
    monthly = []
    for loan in loans:
        ln          = loan['loan_number']
        orig_amount = loan.get('orig_loan_amount') or 300000
        orig_rate   = float(loan.get('orig_interest_rate') or 0.055)
        orig_term   = loan.get('orig_loan_term_months') or 360

        for cycle in cycles_to_include:
            ov        = MONTHLY_ERRORS.get(ln, {}).get(cycle, {})
            idx       = CYCLES.index(cycle)
            cycle_end = date(int(cycle[:4]), int(cycle[4:]), 28)

            upb = int(orig_amount * 1.08) if ov.get('upb_override') \
                  else int(orig_amount * (1 - idx * 0.004))

            curr_rate = ov.get('rate_override', orig_rate)
            fico_curr = ov.get('fico_score_current', random.randint(640, 800))
            fico_date = (cycle_end - timedelta(days=120)) if ov.get('fico_date_stale') \
                        else (cycle_end - timedelta(days=random.randint(15, 45)))

            mod_type  = ov.get('modification_type', 0)
            lm_status = ov.get('loss_mitigation_status',
                                '1' if mod_type > 0 else '0')
            rem_term  = max(1, orig_term - (idx + 1) * 6)

            try:
                mr = curr_rate / 12
                pi = int(upb * mr / (1 - (1 + mr) ** (-rem_term)))
            except Exception:
                pi = 1500

            delinq_status = ov.get('delinquency_status', '0')
            delinq_days   = ov.get('delinquency_days',   0)
            npd = date(int(cycle[:4]), int(cycle[4:]), 1) + timedelta(days=random.randint(0, 27))

            monthly.append({
                'loan_number':               ln,
                'reporting_asof_month':      cycle,
                'upb_current':               upb,
                'current_interest_rate':     curr_rate,
                'remaining_term_months':     rem_term,
                'pi_amount_current':         pi,
                'actual_payment_amount':     pi if delinq_days == 0 else int(pi * 0.5),
                'escrow_amount_current':     random.randint(0, 600),
                'next_payment_due_date':     npd,
                'io_flag_current':           'N',
                'interest_type_current':     loan.get('interest_type_orig', '1'),
                'fico_score_current':        fico_curr,
                'fico_date_current':         fico_date,
                'fico_vendor_current':       '1',
                'investor_type':             loan.get('investor_type', '1'),
                'foreclosure_status':        ov.get('foreclosure_status', '0'),
                'foreclosure_referral_date': ov.get('foreclosure_referral_date', None),
                'loss_mitigation_status':    lm_status,
                'bankruptcy_flag':           ov.get('bankruptcy_flag', 'N'),
                'bankruptcy_chapter':        ov.get('bankruptcy_chapter', None),
                'modification_type':         mod_type,
                'last_modified_date':        date(2024, 6, 15) if mod_type > 0 else None,
                'delinquency_status':        delinq_status,
                'delinquency_days':          delinq_days,
                'paid_in_full_code':         'N',
            })
    return monthly


# ─────────────────────────────────────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def truncate_all(cur):
    print("  Truncating all tables...")
    cur.execute("""
        TRUNCATE TABLE
            y14m_sentinel.issue_tracker,
            y14m_sentinel.ai_analysis_results,
            y14m_sentinel.validation_errors,
            y14m_sentinel.validation_runs,
            y14m_sentinel.schedule_a_loans_monthly,
            y14m_sentinel.schedule_a_loans_orig
        RESTART IDENTITY CASCADE
    """)


def insert_loans(cur, loans, label=''):
    if not loans:
        return
    psycopg2.extras.execute_values(
        cur,
        f"INSERT INTO y14m_sentinel.schedule_a_loans_orig "
        f"({', '.join(ORIG_COLS)}) VALUES %s "
        f"ON CONFLICT (loan_number) DO NOTHING",
        [tuple(l.get(c) for c in ORIG_COLS) for l in loans],
        page_size=200
    )
    print(f"    Inserted {len(loans)} {label}")


def insert_monthly(cur, monthly, label=''):
    if not monthly:
        return
    update_cols = [c for c in MONTHLY_COLS
                   if c not in ('loan_number', 'reporting_asof_month')]
    update_str  = ', '.join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    psycopg2.extras.execute_values(
        cur,
        f"INSERT INTO y14m_sentinel.schedule_a_loans_monthly "
        f"({', '.join(MONTHLY_COLS)}) VALUES %s "
        f"ON CONFLICT (loan_number, reporting_asof_month) DO UPDATE SET {update_str}",
        [tuple(m.get(c) for c in MONTHLY_COLS) for m in monthly],
        page_size=500
    )
    print(f"    Upserted {len(monthly)} monthly records {label}")


def remove_fixed_loans(cur, loan_numbers, label=''):
    """
    Remove loans that the team has 'fixed' between cycles.
    Must delete monthly first (FK constraint).
    """
    cur.execute(
        "DELETE FROM y14m_sentinel.schedule_a_loans_monthly WHERE loan_number = ANY(%s)",
        (loan_numbers,)
    )
    cur.execute(
        "DELETE FROM y14m_sentinel.schedule_a_loans_orig WHERE loan_number = ANY(%s)",
        (loan_numbers,)
    )
    print(f"    Removed {len(loan_numbers)} {label}")


def count_orig(cur):
    cur.execute("SELECT COUNT(*) FROM y14m_sentinel.schedule_a_loans_orig")
    return cur.fetchone()[0]


def print_score_table(cur):
    cur.execute("""
        SELECT reporting_cycle, readiness_score,
               critical_count, high_count, medium_count, total_errors, total_loans
        FROM y14m_sentinel.validation_runs
        ORDER BY reporting_cycle
    """)
    rows = cur.fetchall()
    if not rows:
        print("  No validation runs yet.")
        return
    print(f"\n  {'Cycle':<10} {'Score':<8} {'CRIT':<6} {'HIGH':<6} {'MED':<6} "
          f"{'ERRORS':<8} {'LOANS':<8} {'Trend'}")
    print(f"  {'-'*62}")
    labels = {'202501': 'worst', '202502': 'improving', '202503': 'near ready'}
    for r in rows:
        print(f"  {r[0]:<10} {str(r[1]):<8} {str(r[2]):<6} {str(r[3]):<6} "
              f"{str(r[4]):<6} {str(r[5]):<8} {str(r[6]):<8} {labels.get(r[0],'')}")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':

    print("\nY-14M Sentinel — Data Generator v3 (correct cohort approach)")
    print("=" * 65)
    print("Portfolio GROWS each cycle. Errors fixed between cycles.")
    print("Targets: 202501~60  202502~64  202503~90")
    print()

    loans = build_all_loans()

    c1_clean         = loans['c1_clean']         # 120 loans — base portfolio
    c1_errors        = loans['c1_errors']         # 7 error loans
    c1_fix_before_c2 = loans['c1_fix_before_c2'] # 4 loan numbers to remove after C1
    c2_clean         = loans['c2_clean']          # 40 new Feb 2025 loans
    c2_errors        = loans['c2_errors']         # 2 new error loans
    c3_clean         = loans['c3_clean']          # 30 new Mar 2025 loans

    conn = get_conn()
    cur  = conn.cursor()

    try:
        truncate_all(cur)
        conn.commit()
        print("  Tables truncated.\n")

        # ─────────────────────────────────────────────────────────────────────
        # CYCLE 202501
        # Portfolio: 120 clean + 7 errors = 127 loans
        # Errors: R005(C) R003(H) R007(H) R013(H) R008(M) R009(M) R015(M)
        # Monthly: R006(M) R017(M)
        # Score: 100-15-15-10 = 60
        # ─────────────────────────────────────────────────────────────────────
        print("─" * 65)
        print("  SEEDING CYCLE 202501")
        print("  Portfolio: 120 clean + 7 error loans = 127 total")

        insert_loans(cur, c1_clean,  '202501 clean loans')
        insert_loans(cur, c1_errors, '202501 error loans')

        # Monthly records: C1 loans appear in all 3 cycles
        # C1 error loans also appear in all cycles (until deleted)
        m_c1_clean  = build_monthly_for(c1_clean,  ['202501','202502','202503'])
        m_c1_errors = build_monthly_for(c1_errors, ['202501','202502','202503'])
        insert_monthly(cur, m_c1_clean,  'for C1 clean loans')
        insert_monthly(cur, m_c1_errors, 'for C1 error loans')
        conn.commit()
        print(f"  Orig table now: {count_orig(cur)} loans\n")

        print("  ► Run validate.py — enter: 202501")
        input("  Press Enter when 202501 validation is COMPLETE > ")
        print()

        # ─────────────────────────────────────────────────────────────────────
        # BETWEEN CYCLES 1 AND 2
        # Simulate team remediation: CRIT and HIGH errors fixed
        # Remove R005, R003, R007, R013 from orig (team corrected the data)
        # ─────────────────────────────────────────────────────────────────────
        print("  Simulating remediation: removing fixed C/H errors...")
        remove_fixed_loans(cur, c1_fix_before_c2,
                           'cycle 1 C/H errors (team fixed these)')
        conn.commit()
        print(f"  Orig table now: {count_orig(cur)} loans (3 M errors remain unfixed)\n")

        # ─────────────────────────────────────────────────────────────────────
        # CYCLE 202502
        # Portfolio: 120-4=116 base + 3 unfixed M errors + 40 new + 2 new errors
        #          = 161 loans
        # New origination errors: R012(C) R014(H)
        # Monthly: R021(H) R022(H)
        # Origination errors active: R008(M) R009(M) R015(M) + R012(C) R014(H)
        # Score: 100-15-(1H+2H)-(3M) = 100-15-15-6 = 64
        # ─────────────────────────────────────────────────────────────────────
        print("─" * 65)
        print("  SEEDING CYCLE 202502")
        print("  Adding: 40 new clean + 2 new error loans")

        insert_loans(cur, c2_clean,  '202502 new clean loans (Feb 2025 originations)')

        # R012 has lien constraint issue? No — R011 had that.
        # R012 is LTV mismatch — no constraint issue.
        # Drop chk_lien_position not needed for C2 errors (no lien_position=2 here)
        insert_loans(cur, c2_errors, '202502 new error loans')

        # Monthly records for NEW loans — only cycles 202502 and 202503
        m_c2_clean  = build_monthly_for(c2_clean,  ['202502','202503'])
        m_c2_errors = build_monthly_for(c2_errors, ['202502','202503'])
        insert_monthly(cur, m_c2_clean,  'for C2 clean loans')
        insert_monthly(cur, m_c2_errors, 'for C2 error loans')
        conn.commit()
        print(f"  Orig table now: {count_orig(cur)} loans\n")

        print("  ► Run validate.py — enter: 202502")
        input("  Press Enter when 202502 validation is COMPLETE > ")
        print()

        # Between C2 and C3: team fixes C2 errors (C and H priority)
        c2_fix_before_c3 = ['LN-E2-R012', 'LN-E2-R014']
        print("  Simulating remediation: removing fixed C2 errors...")
        remove_fixed_loans(cur, c2_fix_before_c3,
                           'cycle 2 C/H errors (team fixed these)')
        conn.commit()
        print(f"  Orig table now: {count_orig(cur)} loans\n")

        # ─────────────────────────────────────────────────────────────────────
        # CYCLE 202503
        # Portfolio: 161-2=159 + 30 new clean = 189 loans
        # Only R008(M) R009(M) R015(M) remain from C1 (unfixed M errors)
        # Monthly: R020(M) R024(M)
        # Score: 100-0-0-(3+2)*2 = 100-10 = 90
        # ─────────────────────────────────────────────────────────────────────
        print("─" * 65)
        print("  SEEDING CYCLE 202503")
        print("  Adding: 30 new clean loans (Mar 2025 originations)")

        insert_loans(cur, c3_clean, '202503 new clean loans (Mar 2025 originations)')

        m_c3_clean = build_monthly_for(c3_clean, ['202503'])
        insert_monthly(cur, m_c3_clean, 'for C3 clean loans')
        conn.commit()
        print(f"  Orig table now: {count_orig(cur)} loans\n")

        print("  ► Run validate.py — enter: 202503")
        input("  Press Enter when 202503 validation is COMPLETE > ")
        print()

        # ─────────────────────────────────────────────────────────────────────
        # FINAL VERIFICATION
        # ─────────────────────────────────────────────────────────────────────
        print("─" * 65)
        print("  FINAL STATE")
        cur.execute("SELECT COUNT(*) FROM y14m_sentinel.schedule_a_loans_orig")
        print(f"  Orig loans remaining : {cur.fetchone()[0]}")
        cur.execute("SELECT COUNT(*) FROM y14m_sentinel.schedule_a_loans_monthly")
        print(f"  Monthly records      : {cur.fetchone()[0]}")
        print()
        print("  PORTFOLIO GROWTH ACROSS CYCLES:")
        print("  202501: 127 loans (120 clean + 7 errors)")
        print("  202502: 161 loans (+40 new clean +2 new errors, 4 C1 fixed)")
        print("  202503: 189 loans (+30 new clean, 2 C2 fixed)")
        print()
        print_score_table(cur)

    except Exception as e:
        conn.rollback()
        print(f"\n  ERROR: {e}")
        raise

    finally:
        cur.close()
        conn.close()

    print("\n  Next steps:")
    print("  python issue_tracker_final.py")
    print("  python ai_analysis_final.py")
    print("  Refresh Power BI\n")

    print("  EXPECTED SCORES:")
    print("  202501 ~60 : 1C+3H+3M origination + 2M monthly = 1C+3H+5M")
    print("  202502 ~64 : 1C+1H origination + 3M persist + 2H monthly = 1C+3H+3M")
    print("  202503 ~90 : 0C+0H origination + 3M persist + 2M monthly = 0C+0H+5M")
