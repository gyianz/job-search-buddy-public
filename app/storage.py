import hashlib
import shutil
from pathlib import Path


def job_id_for_url(url: str) -> str:
    """Generate a stable job ID from a URL using the first 12 hex chars of SHA1."""
    sha1_hash = hashlib.sha1(url.encode()).hexdigest()
    return sha1_hash[:12]


def job_dir(job_id: str, base: Path = Path("jobs")) -> Path:
    """Return the path to the job directory for a given job ID."""
    return base / job_id


def write_posting(job_id: str, markdown: str, base: Path = Path("jobs")) -> Path:
    """Create a job folder and write the posting markdown file."""
    posting_dir = job_dir(job_id, base)
    posting_dir.mkdir(parents=True, exist_ok=True)
    posting_path = posting_dir / "posting.md"
    posting_path.write_text(markdown)
    return posting_path


def read_profile(path: Path = Path("profile/profile.md")) -> str:
    """Read the profile markdown file. Raises FileNotFoundError if the file doesn't exist."""
    if not path.exists():
        raise FileNotFoundError(f"Profile file not found: {path}")
    return path.read_text()


TRASH_DIRNAME = ".trash"


def trash_path(job_id: str, base: Path = Path("jobs")) -> Path:
    """Where a deleted job's folder is kept: jobs/.trash/<id>."""
    return base / TRASH_DIRNAME / job_id


def is_trashed(job_id: str, base: Path = Path("jobs")) -> bool:
    """True if the job was deleted; fetch uses this so it doesn't re-add it."""
    return trash_path(job_id, base).exists()


def move_to_trash(job_id: str, base: Path = Path("jobs")) -> Path:
    """Move jobs/<id> to jobs/.trash/<id>, leaving a marker if there's no folder.

    The folder (posting plus any tailored resume / cover letter) is kept so a
    deletion can be undone by moving it back.
    """
    dest = trash_path(job_id, base)
    src = job_dir(job_id, base)
    if src.is_dir():
        if dest.exists():
            shutil.rmtree(dest)  # An older deletion of the same job.
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
    else:
        dest.mkdir(parents=True, exist_ok=True)
    return dest
