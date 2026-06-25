# run.py
# CLI entry point: python -m agent.run [--seed] [--full] [--job-id <id>]

import argparse
from agent.db import init_schema, create_job
from agent.seed_keywords import seed_keywords
from agent.pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Westpac Sales Scraper Agent")
    parser.add_argument("--seed", action="store_true", help="Seed keywords from PDF defaults")
    parser.add_argument("--full", action="store_true", help="Run full pipeline (all 6 metros)")
    parser.add_argument("--job-id", type=str, default=None, help="Override job_id (else new UUID)")
    parser.add_argument("--init-db", action="store_true", help="Just init DB schema")
    args = parser.parse_args()

    if args.init_db:
        init_schema()
        return

    if args.seed:
        seed_keywords()
        return

    if args.full:
        init_schema()
        seed_keywords()
        job_id = args.job_id or create_job()
        print(f"🚀 Starting pipeline with job_id={job_id}")
        run_pipeline(job_id)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
