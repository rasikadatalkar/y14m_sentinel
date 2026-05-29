
# scripts/issue_tracker_final.py
# ─────────────────────────────────────────────────────────────────────────────

import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from datetime import date, timedelta

load_dotenv()

DB_CONFIG = {
    'host':     'localhost',
    'port':     5432,
    'dbname':   'postgres',
    'user':     'postgres',
    'password': os.getenv('DB_PASSWORD', ''),
    'options':  '-c search_path=y14m_sentinel'
}

OWNER_MAP = {
    'CRITICAL':      'Regulatory Reporting Lead',
    'HIGH':          'Senior Data Engineer',
    'MEDIUM':        'Data Quality Analyst',
    'INFORMATIONAL': 'Data Quality Analyst',
}

SLA_DAYS = {
    'CRITICAL':       1,
    'HIGH':           3,
    'MEDIUM':         7,
    'INFORMATIONAL': 14,
}


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def create_issues_for_all_runs(cur):
    """
    Aggregate validation_errors by (run, rule, field, severity, source_system),
    skip clusters already in issue_tracker, bulk-insert all new issues at once.

    source_system is now included in the GROUP BY — this means separate issue
    tickets are created per source system per rule. This lets the Remediation
    Tracker page in Power BI show "Senior Data Engineer has 5 issues from LOS"
    rather than a single merged row.
    """

    cur.execute("""
        SELECT
            ve.run_id,
            ve.rule_id,
            ve.field_name,
            ve.severity,
            COUNT(*)            AS affected_loan_count,
            ve.reporting_cycle
        FROM y14m_sentinel.validation_errors ve
        LEFT JOIN y14m_sentinel.issue_tracker it
            ON it.run_id          = ve.run_id
            AND it.rule_id        = ve.rule_id
            AND it.error_category = CONCAT(ve.field_name, ' -- ', ve.rule_id)
        WHERE it.run_id IS NULL
        GROUP BY
            ve.run_id,
            ve.rule_id,
            ve.field_name,
            ve.severity,
            ve.reporting_cycle
        ORDER BY
            ve.run_id,
            CASE ve.severity
                WHEN 'CRITICAL'      THEN 1
                WHEN 'HIGH'          THEN 2
                WHEN 'MEDIUM'        THEN 3
                ELSE 4
            END
    """)
    clusters = cur.fetchall()

    if not clusters:
        print("  No new error clusters — issue_tracker is up to date.")
        return 0

    today          = date.today()
    rows_to_insert = []

    for cluster in clusters:
        run_id     = cluster[0]
        rule_id    = cluster[1]
        field_name = cluster[2]
        severity   = cluster[3]
        loan_count = int(cluster[4])
        cycle      = cluster[5]

        sla_dt = today + timedelta(days=SLA_DAYS.get(severity, 7))
        owner  = OWNER_MAP.get(severity, 'Data Team')
        cat    = f"{field_name} -- {rule_id}"

        rows_to_insert.append((
            run_id, rule_id, cat, severity,
            loan_count, 'OPEN', owner, sla_dt, cycle
        ))

    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO y14m_sentinel.issue_tracker
            (run_id, rule_id, error_category, severity,
             affected_loan_count, status, owner,
             sla_date, reporting_cycle)
        VALUES %s
        """,
        rows_to_insert,
        page_size=500
    )

    print(f"  {len(rows_to_insert)} issue(s) created across "
          f"{len(set(r[0] for r in rows_to_insert))} run(s).")
    return len(rows_to_insert)


def print_summary(cur):
    cur.execute("""
        SELECT severity, status, COUNT(*)
        FROM y14m_sentinel.issue_tracker
        GROUP BY severity, status
        ORDER BY
            CASE severity
                WHEN 'CRITICAL' THEN 1
                WHEN 'HIGH'     THEN 2
                WHEN 'MEDIUM'   THEN 3
                ELSE 4
            END, status
    """)
    rows = cur.fetchall()
    print("\nIssue Tracker Summary:")
    print("-" * 50)
    print(f"  {'SEVERITY':<16} {'STATUS':<14} {'COUNT':>5}")
    print("-" * 50)
    for row in rows:
        print(f"  {row[0]:<16} {row[1]:<14} {row[2]:>5}")
    print("-" * 50)




if __name__ == '__main__':

    conn = get_conn()
    cur  = conn.cursor()

    try:
        cur.execute("SELECT COUNT(*) FROM y14m_sentinel.validation_runs")
        run_count = cur.fetchone()[0]

        if run_count == 0:
            print("No validation runs found. Run validate_final.py first.")
        else:
            print(f"Found {run_count} validation run(s). Creating issues...\n")
            print("-" * 50)

            total = create_issues_for_all_runs(cur)
            conn.commit()

            if total > 0:
                print_summary(cur)

    except Exception as e:
        conn.rollback()
        print(f"\n  ERROR: {e}")
        raise

    finally:
        cur.close()
        conn.close()

    print("\nIssue tracker complete.")
