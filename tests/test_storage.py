from pathlib import Path
from app.storage import job_id_for_url, job_dir, write_posting, read_profile

def test_job_id_is_stable_for_same_url():
    assert job_id_for_url("https://x.example/1") == job_id_for_url("https://x.example/1")
    assert job_id_for_url("https://x.example/1") != job_id_for_url("https://x.example/2")
    assert len(job_id_for_url("https://x.example/1")) == 12

def test_write_posting_creates_file(tmp_path):
    path = write_posting("abc123", "# Title\n\nBody", base=tmp_path)
    assert path == tmp_path / "abc123" / "posting.md"
    assert path.read_text() == "# Title\n\nBody"

def test_read_profile_missing_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        read_profile(tmp_path / "nope.md")

def test_read_profile_reads_existing(tmp_path):
    p = tmp_path / "profile.md"
    p.write_text("# Me")
    assert read_profile(p) == "# Me"
