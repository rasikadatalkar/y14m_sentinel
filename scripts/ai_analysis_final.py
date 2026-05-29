# scripts/ai_analysis_final.py
#
import os
import psycopg2
import psycopg2.extras
import anthropic
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

DB_CONFIG = {
    'host':     'localhost',
    'port':     5432,
    'dbname':   'postgres',
    'user':     'postgres',
    'password': os.getenv('DB_PASSWORD', ''),
    'options':  '-c search_path=y14m_sentinel'
}

MODEL      = 'claude-haiku-4-5-20251001'
MAX_TOKENS = 1000

# Client created once — avoids repeated HTTP session setup on every API call
claude_client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


# ── Claude call ───────────────────────────────────────────────────────────────

def call_claude(prompt: str, label: str) -> str:
    """
    Send one prompt to Claude. Returns plain text response.
    On failure returns an error string — one bad call does not lose the run.
    """
    try:
        msg = claude_client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return msg.content[0].text
    except Exception as e:
        print(f"    WARNING: Claude call failed for '{label}': {e}")
        return f"Analysis unavailable — API error: {e}"


# ── Prompt builders ───────────────────────────────────────────────────────────
# Separated so prompts are easy to tune without touching the main logic.
# All prompts instruct Claude to write plain text — no markdown symbols.

def build_pattern_prompt(reporting_cycle: str, error_table: str) -> str:
    return f"""You are a regulatory data quality analyst at a US bank reviewing FR Y-14M Schedule A mortgage data.
Below is a table of validation errors found in reporting cycle {reporting_cycle}.
Write 3-5 sentences in plain text only identifying the dominant error patterns.
Call out which source systems and which fields are responsible for the most errors.
Be specific with numbers and rule IDs. No markdown, no asterisks, no bullet points, no headers.

Error summary:
{error_table}"""


def build_summary_prompt(reporting_cycle, total_errors, critical, high, medium, readiness) -> str:
    return f"""You are a regulatory reporting analyst writing a brief validation run summary.
Write 2-3 sentences in plain text only that a submission manager would read before filing.
Include total errors, severity breakdown, readiness score, and whether the submission is ready.
No markdown, no asterisks, no bullet points, no headers. Plain sentences only.

Run data:
- Reporting cycle : {reporting_cycle}
- Total errors    : {total_errors}
- CRITICAL        : {critical}
- HIGH            : {high}
- MEDIUM          : {medium}
- Readiness score : {readiness} / 100
- Filing threshold: 85 / 100"""


def build_remed_prompt(top_table: str) -> str:
    return f"""You are a data quality engineer recommending fixes for FR Y-14M validation errors.
For each error category below, write one concrete action to fix it in the source system.
Format exactly as: [Rule ID]: [One sentence action]. No markdown, no asterisks, no bullet points.

Top error categories:
{top_table}"""


# ── Format helper ─────────────────────────────────────────────────────────────

def format_error_table(rows: list) -> str:
    """
    Convert aggregated DB rows into a compact text table for Claude.
    We pass grouped rows (already aggregated by rule/field/severity/source_system)
    NOT raw validation_errors rows. A run with 5000 individual errors still
    produces only ~25 summary rows — keeps token usage low.
    """
    lines = ["rule_id | field_name | severity | source_system | count", "-" * 68]
    for row in rows:
        lines.append(f"{row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]}")
    return "\n".join(lines)


# ── Core analysis ─────────────────────────────────────────────────────────────

def analyse_run(cur, run_id: int):
    """
    Fetch data for one run, fire three Claude prompts in parallel,
    return a tuple ready for DB insert. Returns None if already analysed.
    """

    # Duplicate guard — no point calling Claude if result already exists
    cur.execute("""
        SELECT 1 FROM y14m_sentinel.ai_analysis_results WHERE run_id = %s
    """, (run_id,))
    if cur.fetchone():
        print(f"  run_id={run_id}: already analysed, skipping.")
        return None

    # Aggregated error summary — includes source_system (now reliably populated)
    cur.execute("""
        SELECT rule_id, field_name, severity, source_system, COUNT(*) AS cnt
        FROM y14m_sentinel.validation_errors
        WHERE run_id = %s
        GROUP BY rule_id, field_name, severity, source_system
        ORDER BY cnt DESC
    """, (run_id,))
    error_rows = cur.fetchall()

    # Run header
    cur.execute("""
        SELECT reporting_cycle, total_errors,
               critical_count, high_count, medium_count, readiness_score
        FROM y14m_sentinel.validation_runs
        WHERE run_id = %s
    """, (run_id,))
    run = cur.fetchone()

    if not run:
        print(f"  run_id={run_id}: no validation_runs row found, skipping.")
        return None

    reporting_cycle, total_errors, critical, high, medium, readiness = run

    if not error_rows:
        print(f"  run_id={run_id}: no errors — skipping AI analysis.")
        return None

    # Build prompts
    full_table = format_error_table(error_rows)
    top_table  = format_error_table(error_rows[:5])

    pattern_prompt = build_pattern_prompt(reporting_cycle, full_table)
    summary_prompt = build_summary_prompt(reporting_cycle, total_errors,
                                          critical, high, medium, readiness)
    remed_prompt   = build_remed_prompt(top_table)

    # Fire all three Claude calls in parallel
    # ThreadPoolExecutor is the right tool for I/O-bound calls (waiting on HTTP).
    # Python's GIL does not block I/O threads — true parallelism achieved.
    # Result: ~5s per run instead of ~15s sequential.
    print(f"  run_id={run_id}: firing 3 Claude calls in parallel...")

    jobs = {
        'pattern': pattern_prompt,
        'summary': summary_prompt,
        'remed':   remed_prompt,
    }
    results = {}

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(call_claude, prompt, label): label
            for label, prompt in jobs.items()
        }
        for future in as_completed(futures):
            label          = futures[future]
            results[label] = future.result()
            print(f"    ✓ {label} done")

    return (run_id, results['pattern'], results['summary'], results['remed'])


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':

    conn = get_conn()
    cur  = conn.cursor()

    try:
        cur.execute("""
            SELECT run_id FROM y14m_sentinel.validation_runs ORDER BY run_id
        """)
        run_ids = [row[0] for row in cur.fetchall()]

        if not run_ids:
            print("No validation runs found. Run validate_final.py first.")
        else:
            print(f"Found {len(run_ids)} run(s) to process.\n")
            print("-" * 45)

            rows_to_insert = []
            for run_id in run_ids:
                print(f"\nrun_id={run_id}")
                result = analyse_run(cur, run_id)
                if result:
                    rows_to_insert.append(result)

            # Bulk insert — one DB call for all runs
            if rows_to_insert:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO y14m_sentinel.ai_analysis_results
                        (run_id, pattern_detection, run_summary, remediation_recs)
                    VALUES %s
                    """,
                    rows_to_insert,
                    page_size=100
                )
                conn.commit()
                print(f"\n  {len(rows_to_insert)} run(s) written to ai_analysis_results.")
            else:
                print("\n  Nothing new to write.")

            # Verification
            cur.execute("""
                SELECT ar.run_id, vr.reporting_cycle, vr.readiness_score,
                       LEFT(ar.run_summary, 80) AS preview
                FROM y14m_sentinel.ai_analysis_results ar
                JOIN y14m_sentinel.validation_runs vr ON vr.run_id = ar.run_id
                ORDER BY ar.run_id
            """)
            rows = cur.fetchall()
            print("\nAI Analysis Results:")
            print("-" * 65)
            for row in rows:
                print(f"  run={row[0]} | cycle={row[1]} | score={row[2]} | {row[3]}...")
            print("-" * 65)

    except Exception as e:
        conn.rollback()
        print(f"\n  ERROR: {e}")
        raise

    finally:
        cur.close()
        conn.close()

    print("\nAI analysis complete.")
