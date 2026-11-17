import argparse
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

from app.db import connect, init_db, insert_job, list_jobs, get_job, set_score, set_tailored_paths
from app.ats.fetch import fetch_all
from app.boards import load_boards
from app.jobs_folder import add_job, sync_jobs_folder
from app.rubric import load_rubric, to_markdown
from app.storage import job_id_for_url, write_posting

VALID_BUCKETS = {"match", "stretch", "no_fit"}


def _db_path() -> str:
    return os.environ.get("JSB_DB_PATH", "data/app.db")


def _connect() -> "sqlite3.Connection":
    conn = connect(_db_path())
    init_db(conn)
    # Make jobs saved to the jobs/ folder visible to every command.
    sync_jobs_folder(conn, Path(os.environ.get("JSB_JOBS_DIR", "jobs")))
    return conn


def cmd_fetch(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        result = fetch_all(conn, load_boards())
    finally:
        conn.close()
    print(f"inserted: {result['inserted']}, errors: {result['errors']}")
    return 0


def cmd_pending(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        jobs = list_jobs(conn)
    finally:
        conn.close()
    for job in jobs:
        flags = []
        if job.get("needs_scoring"):
            flags.append("needs_scoring")
        if job.get("needs_tailoring"):
            flags.append("needs_tailoring")
        if args.unscored and not job.get("score_bucket") and not job.get("needs_scoring"):
            flags.append("unscored")
        if flags:
            print(f"{job['id']} {job['company']} - {job['title']} [{'|'.join(flags)}]")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    if args.bucket not in VALID_BUCKETS:
        print(f"error: bucket must be one of {sorted(VALID_BUCKETS)}, got '{args.bucket}'")
        return 1
    rationale = " ".join(args.rationale)
    criteria = {
        key: getattr(args, f"crit_{key}")
        for key in args.criteria_keys
        if getattr(args, f"crit_{key}") is not None
    }
    conn = _connect()
    try:
        set_score(conn, args.job_id, args.bucket, rationale, criteria, args.salary_estimate)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    finally:
        conn.close()
    return 0


def cmd_rubric(args: argparse.Namespace) -> int:
    print(to_markdown(load_rubric()))
    return 0


def cmd_tailor(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        set_tailored_paths(conn, args.job_id, args.resume_path, args.cover_letter_path)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    finally:
        conn.close()
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        job_id, created = add_job(
            conn,
            company=args.company,
            title=args.title,
            url=args.url,
            location=args.location,
            base=Path(os.environ.get("JSB_JOBS_DIR", "jobs")),
        )
    finally:
        conn.close()
    if created:
        print(f"inserted {job_id}")
    else:
        print(f"duplicate (already tracked as {job_id})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jsb")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_fetch = subparsers.add_parser("fetch")
    p_fetch.set_defaults(func=cmd_fetch)

    p_pending = subparsers.add_parser("pending")
    p_pending.add_argument(
        "--unscored", action="store_true",
        help="also list jobs that have never been scored (e.g. fresh from fetch)",
    )
    p_pending.set_defaults(func=cmd_pending)

    p_score = subparsers.add_parser("score")
    p_score.add_argument("job_id")
    p_score.add_argument("bucket")
    p_score.add_argument("rationale", nargs="+")
    # One flag per criterion in profile/rubric.json (see `rubric`).
    criteria = load_rubric()["criteria"]
    for criterion in criteria:
        p_score.add_argument(
            f"--{criterion['key']}", dest=f"crit_{criterion['key']}",
            type=int, choices=range(1, 6), metavar="1-5",
            help=f"{criterion['label']} score (see `rubric`)",
        )
    p_score.set_defaults(criteria_keys=[c["key"] for c in criteria])
    p_score.add_argument("--salary-estimate", help='e.g. "$170k-$190k base (est.)"')
    p_score.set_defaults(func=cmd_score)

    p_rubric = subparsers.add_parser("rubric", help="print the scoring rubric")
    p_rubric.set_defaults(func=cmd_rubric)

    p_tailor = subparsers.add_parser("tailor")
    p_tailor.add_argument("job_id")
    p_tailor.add_argument("resume_path")
    p_tailor.add_argument("cover_letter_path")
    p_tailor.set_defaults(func=cmd_tailor)

    p_add = subparsers.add_parser("add")
    p_add.add_argument("company")
    p_add.add_argument("title")
    p_add.add_argument("url")
    p_add.add_argument("location", nargs="?", default=None)
    p_add.set_defaults(func=cmd_add)

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
