# scripts/validate_final.py
#
# ─────────────────────────────────────────────────────────────────────────────

import psycopg2
import json
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    'host':     'localhost',
    'port':     5432,
    'dbname':   'postgres',
    'user':     'postgres',
    'password': os.getenv('DB_PASSWORD', ''),
    'options':  '-c search_path=y14m_sentinel'
}


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def load_rules():
    """
    Load validation rules from JSON.
    Opens with UTF-8 encoding explicitly and strips BOM if present.
    Falls back to cp1252 if UTF-8 fails — handles JSON files saved
    on Windows with the wrong encoding.
    """
    rules_path = Path(__file__).parent.parent / 'config' / 'validation_rules.json'
    try:
        with open(rules_path, encoding='utf-8-sig') as f:
            return json.load(f)['rules']
    except (UnicodeDecodeError, ValueError):
        with open(rules_path, encoding='cp1252') as f:
            return json.load(f)['rules']


def compute_readiness_score(critical, high, medium):
    score = 100 - (critical * 15) - (high * 5) - (medium * 2)
    return max(0, round(score, 1))



def sanitize_msg(msg):
    """
    Sanitize error messages to pure ASCII before writing to DB.
    Handles: Unicode special chars, Windows-1252 bytes, UTF-8 misread as Latin-1.
    Belt-and-suspenders: known replacements first, then strip all non-ASCII bytes.
    """
    if not msg:
        return msg

    # Unicode replacements (em-dash, curly quotes, ellipsis)
    for old, new in [
        ('\u2014', '--'), ('\u2013', '-'),
        ('\u2018', "'"), ('\u2019', "'"),
        ('\u201c', '"'), ('\u201d', '"'),
        ('\u2026', '...'), ('\u00e2', ''), ('\u20ac', ''), ('\u0080', ''),
    ]:
        msg = msg.replace(old, new)

    # Windows-1252 raw bytes
    for old, new in [
        ('\x97', '--'), ('\x96', '-'), ('\x93', '"'), ('\x94', '"'),
        ('\x91', "'"), ('\x92', "'"),
    ]:
        msg = msg.replace(old, new)

    # Strip ALL remaining non-ASCII
    msg = msg.encode('ascii', 'ignore').decode('ascii')

    # Collapse double spaces
    while '  ' in msg:
        msg = msg.replace('  ', ' ')

    return msg.strip()


def run_validation(reporting_cycle):
    rules  = load_rules()
    errors = []

    conn = get_conn()
    cur  = conn.cursor()

    try:
        # ── Register this run ─────────────────────────────────────────────────
        cur.execute("""
            SELECT run_id FROM y14m_sentinel.validation_runs
            ORDER BY run_id DESC LIMIT 1
        """)
        row = cur.fetchone()
        prior_run_id = row[0] if row else None

        cur.execute("""
            INSERT INTO y14m_sentinel.validation_runs
                (reporting_cycle, run_timestamp, prior_run_id)
            VALUES (%s, %s, %s)
            RETURNING run_id
        """, (reporting_cycle, datetime.now(), prior_run_id))
        run_id = cur.fetchone()[0]
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM y14m_sentinel.schedule_a_loans_orig")
        total_loans = cur.fetchone()[0]
        print(f"  Run ID: {run_id}  |  Cycle: {reporting_cycle}  |  Loans: {total_loans}")

        # ── Run each rule ─────────────────────────────────────────────────────
        for rule in rules:
            rule_id  = rule['rule_id']
            severity = rule['severity']
            err_msg  = rule['error_message']

            try:

                # ── ORIGINATION RULES ─────────────────────────────────────────
                # All query schedule_a_loans_orig which has source_system.
                # NOTE: paid_in_full_code no longer in orig — removed from R003 list.

                if rule_id == 'R003':
                    # Required fields — paid_in_full_code removed (now in monthly)
                    # commercial_loan_flag, sbo_flag, entity_serviced removed entirely
                    for field in [
                        'loan_closing_date', 'orig_loan_amount', 'orig_property_value',
                        'original_ltv', 'fico_score_orig', 'property_state',
                        'property_type', 'occupancy_status', 'lien_position', 'investor_type'
                    ]:
                        cur.execute(f"""
                            SELECT loan_number, source_system
                            FROM y14m_sentinel.schedule_a_loans_orig
                            WHERE {field} IS NULL
                        """)
                        for row in cur.fetchall():
                            errors.append((run_id, str(row[0]), rule_id, field,
                                           'NULL', severity, sanitize_msg(f'{field} is blank'),
                                           reporting_cycle, str(row[1])))

                elif rule_id == 'R004':
                    cur.execute("""
                        SELECT loan_number, loan_closing_date, source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE loan_closing_date IS NULL
                        OR loan_closing_date > CURRENT_DATE
                        OR loan_closing_date < '1970-01-01'
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'loan_closing_date',
                                       str(row[1]), severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[2])))

                elif rule_id == 'R005':
                    # Updated: allows Fed special codes 9997 9998 9999
                    # Explicit IN(0,999) catches old sentinel values
                    cur.execute("""
                        SELECT loan_number, fico_score_orig, source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE fico_score_orig < 300
                        OR (fico_score_orig > 850 AND fico_score_orig NOT IN (9997, 9998, 9999))
                        OR fico_score_orig IN (0, 999)
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'fico_score_orig',
                                       str(row[1]), severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[2])))

                elif rule_id == 'R007':
                    valid_states = tuple(rule['allowed_values'])
                    cur.execute("""
                        SELECT loan_number, property_state, source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE TRIM(property_state) NOT IN %s
                    """, (valid_states,))
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'property_state',
                                       str(row[1]), severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[2])))

                elif rule_id == 'R008':
                    cur.execute("""
                        SELECT loan_number, property_zip, source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE property_zip !~ '^[0-9]{5}$'
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'property_zip',
                                       str(row[1]), severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[2])))

                elif rule_id == 'R009':
                    cur.execute("""
                        SELECT loan_number, orig_loan_amount, source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE orig_loan_amount IS NULL OR orig_loan_amount <= 0
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'orig_loan_amount',
                                       str(row[1]), severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[2])))

                elif rule_id == 'R010':
                    cur.execute("""
                        SELECT loan_number, original_ltv, source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE original_ltv < 0.01 OR original_ltv > 1.05
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'original_ltv',
                                       str(row[1]), severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[2])))

                elif rule_id == 'R011':
                    # NOTE: DB constraint chk_lien_position also enforces this.
                    # Rule kept for human-readable error messages in validation_errors.
                    cur.execute("""
                        SELECT loan_number, lien_position, source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE lien_position != '1'
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'lien_position',
                                       str(row[1]), severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[2])))

                elif rule_id == 'R012':
                    cur.execute("""
                        SELECT loan_number, original_ltv,
                               ROUND(orig_loan_amount::NUMERIC / orig_property_value, 4) AS computed_ltv,
                               source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE orig_property_value > 0
                        AND ABS(original_ltv - ROUND(orig_loan_amount::NUMERIC / orig_property_value, 4)) > 0.01
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'original_ltv',
                                       str(row[1]),
                                       severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[3])))

                elif rule_id == 'R013':
                    cur.execute("""
                        SELECT loan_number, loan_closing_date, first_payment_date, source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE first_payment_date IS NOT NULL
                        AND (first_payment_date <= loan_closing_date
                        OR (first_payment_date - loan_closing_date) < 15
                        OR (first_payment_date - loan_closing_date) > 75)
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'first_payment_date',
                                       str(row[2]), severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[3])))

                elif rule_id == 'R014':
                    cur.execute("""
                        SELECT loan_number, original_cltv, original_ltv, source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE original_cltv IS NOT NULL
                        AND original_cltv < original_ltv
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'original_cltv',
                                       str(row[1]),
                                       severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[3])))

                elif rule_id == 'R015':
                    # dti columns now NUMERIC(5,2) — comparison still works fine
                    cur.execute("""
                        SELECT loan_number, dti_back_end_orig, dti_front_end_orig, source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE dti_back_end_orig IS NOT NULL
                        AND dti_front_end_orig IS NOT NULL
                        AND dti_back_end_orig < dti_front_end_orig
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'dti_back_end_orig',
                                       str(row[1]),
                                       severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[3])))

                elif rule_id == 'R016':
                    cur.execute("""
                        SELECT loan_number, product_type_orig, interest_type_orig, source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE (product_type_orig IN ('4','5','6') AND interest_type_orig = '1')
                        OR    (product_type_orig IN ('1','2','3') AND interest_type_orig = '2')
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'interest_type_orig',
                                       str(row[2]),
                                       severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[3])))

                elif rule_id == 'R018':
                    cur.execute("""
                        SELECT loan_number, io_flag_orig, io_term_orig_months, source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE (io_flag_orig = 'N' AND io_term_orig_months > 0)
                        OR    (io_flag_orig = 'Y' AND (io_term_orig_months IS NULL
                               OR io_term_orig_months = 0))
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'io_flag_orig',
                                       str(row[2]),
                                       severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[3])))

                elif rule_id == 'R019':
                    cur.execute("""
                        SELECT loan_number, balloon_flag, balloon_term_months, source_system
                        FROM y14m_sentinel.schedule_a_loans_orig
                        WHERE (balloon_flag = 'Y' AND (balloon_term_months IS NULL
                               OR balloon_term_months <= 0))
                        OR    (balloon_flag = 'N' AND balloon_term_months IS NOT NULL)
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'balloon_flag',
                                       str(row[2]),
                                       severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[3])))

                # ── MONTHLY RULES ─────────────────────────────────────────────
                # schedule_a_loans_monthly has NO source_system column.
                # All monthly rules JOIN to schedule_a_loans_orig to get source_system.
                # loan_number is PK on orig — this join is an indexed lookup, not a scan.

                elif rule_id == 'R006':
                    cur.execute("""
                        SELECT m.loan_number, m.fico_score_current, o.source_system
                        FROM y14m_sentinel.schedule_a_loans_monthly m
                        JOIN y14m_sentinel.schedule_a_loans_orig o
                            ON m.loan_number = o.loan_number
                        WHERE m.reporting_asof_month = %s
                        AND m.fico_score_current IS NOT NULL
                        AND (m.fico_score_current < 300 OR m.fico_score_current > 850)
                    """, (reporting_cycle,))
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'fico_score_current',
                                       str(row[1]), severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[2])))

                elif rule_id == 'R017':
                    cur.execute("""
                        SELECT m.loan_number, o.orig_interest_rate,
                               m.current_interest_rate, o.source_system
                        FROM y14m_sentinel.schedule_a_loans_monthly m
                        JOIN y14m_sentinel.schedule_a_loans_orig o
                            ON m.loan_number = o.loan_number
                        WHERE m.reporting_asof_month = %s
                        AND o.interest_type_orig = '1'
                        AND m.modification_type = 0
                        AND ABS(m.current_interest_rate - o.orig_interest_rate) > 0.0001
                    """, (reporting_cycle,))
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'current_interest_rate',
                                       str(row[2]),
                                       severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[3])))

                elif rule_id == 'R020':
                    cur.execute("""
                        SELECT m.loan_number, m.upb_current,
                               o.orig_loan_amount, o.source_system
                        FROM y14m_sentinel.schedule_a_loans_monthly m
                        JOIN y14m_sentinel.schedule_a_loans_orig o
                            ON m.loan_number = o.loan_number
                        WHERE m.reporting_asof_month = %s
                        AND m.upb_current > o.orig_loan_amount
                    """, (reporting_cycle,))
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'upb_current',
                                       str(row[1]),
                                       severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[3])))

                elif rule_id == 'R021':
                    cur.execute("""
                        SELECT m.loan_number, m.bankruptcy_flag, o.source_system
                        FROM y14m_sentinel.schedule_a_loans_monthly m
                        JOIN y14m_sentinel.schedule_a_loans_orig o
                            ON m.loan_number = o.loan_number
                        WHERE m.reporting_asof_month = %s
                        AND m.bankruptcy_flag = 'Y'
                        AND (m.bankruptcy_chapter IS NULL OR TRIM(m.bankruptcy_chapter) = '')
                    """, (reporting_cycle,))
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'bankruptcy_chapter',
                                       'NULL', severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[2])))

                elif rule_id == 'R022':
                    cur.execute("""
                        SELECT m.loan_number, m.foreclosure_status, o.source_system
                        FROM y14m_sentinel.schedule_a_loans_monthly m
                        JOIN y14m_sentinel.schedule_a_loans_orig o
                            ON m.loan_number = o.loan_number
                        WHERE m.reporting_asof_month = %s
                        AND m.foreclosure_status != '0'
                        AND m.foreclosure_referral_date IS NULL
                    """, (reporting_cycle,))
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'foreclosure_referral_date',
                                       'NULL', severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[2])))

                elif rule_id == 'R023':
                    cur.execute("""
                        SELECT m.loan_number, m.modification_type,
                               m.loss_mitigation_status, o.source_system
                        FROM y14m_sentinel.schedule_a_loans_monthly m
                        JOIN y14m_sentinel.schedule_a_loans_orig o
                            ON m.loan_number = o.loan_number
                        WHERE m.reporting_asof_month = %s
                        AND m.modification_type > 0
                        AND m.loss_mitigation_status = '0'
                    """, (reporting_cycle,))
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'modification_type',
                                       str(row[1]),
                                       severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[3])))

                elif rule_id == 'R024':
                    cur.execute("""
                        SELECT m.loan_number, m.fico_date_current, o.source_system
                        FROM y14m_sentinel.schedule_a_loans_monthly m
                        JOIN y14m_sentinel.schedule_a_loans_orig o
                            ON m.loan_number = o.loan_number
                        WHERE m.reporting_asof_month = %s
                        AND m.fico_date_current IS NOT NULL
                        AND (TO_DATE(m.reporting_asof_month, 'YYYYMM') - m.fico_date_current) > 90
                    """, (reporting_cycle,))
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'fico_date_current',
                                       str(row[1]), severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[2])))

                elif rule_id == 'R025':
                    cur.execute("""
                        SELECT m.loan_number, m.reporting_asof_month, o.source_system
                        FROM y14m_sentinel.schedule_a_loans_monthly m
                        JOIN y14m_sentinel.schedule_a_loans_orig o
                            ON m.loan_number = o.loan_number
                        WHERE m.reporting_asof_month !~ '^[0-9]{6}$'
                        OR SUBSTRING(m.reporting_asof_month, 5, 2)::INT NOT BETWEEN 1 AND 12
                        OR SUBSTRING(m.reporting_asof_month, 1, 4)::INT NOT BETWEEN 2010 AND 2030
                    """)
                    for row in cur.fetchall():
                        errors.append((run_id, str(row[0]), rule_id, 'reporting_asof_month',
                                       str(row[1]), severity, sanitize_msg(err_msg),
                                       reporting_cycle, str(row[2])))

                print(f"  {rule_id} ✓")

            except Exception as e:
                print(f"  ERROR in {rule_id}: {e}")

        # ── Write errors ──────────────────────────────────────────────────────
        if errors:
            cur.executemany("""
                INSERT INTO y14m_sentinel.validation_errors
                    (run_id, loan_number, rule_id, field_name,
                     actual_value, severity, error_message, reporting_cycle, source_system)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, errors)
            conn.commit()
            print(f"\n  {len(errors)} errors written to validation_errors")

        # ── Compute readiness score ───────────────────────────────────────────
        c = sum(1 for e in errors if e[5] == 'CRITICAL')
        h = sum(1 for e in errors if e[5] == 'HIGH')
        m = sum(1 for e in errors if e[5] == 'MEDIUM')
        i = sum(1 for e in errors if e[5] == 'INFORMATIONAL')
        score = compute_readiness_score(c, h, m)

        cur.execute("""
            UPDATE y14m_sentinel.validation_runs
            SET critical_count  = %s,
                high_count      = %s,
                medium_count    = %s,
                info_count      = %s,
                total_errors    = %s,
                readiness_score = %s,
                total_loans     = %s
            WHERE run_id = %s
        """, (c, h, m, i, len(errors), score, total_loans, run_id))
        conn.commit()

        print(f"\n  Cycle {reporting_cycle} Summary:")
        print(f"  CRITICAL:{c}  HIGH:{h}  MEDIUM:{m}  INFO:{i}")
        print(f"  Readiness Score : {score}/100")
        print(f"  Total Errors    : {len(errors)}")

    finally:
        cur.close()
        conn.close()

    return run_id, errors


if __name__ == '__main__':
    raw    = input("Enter cycles comma separated (e.g. 202501,202502): ").strip()
    cycles = [c.strip() for c in raw.split(',')]

    for cycle in cycles:
        print(f"\nValidating cycle: {cycle}")
        print("-" * 40)
        run_id, errors = run_validation(cycle)
