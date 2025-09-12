from pathlib import Path

from utils.file_scanner import scan_thread_dir


def test_scan_thread_dir_recurses(tmp_path):
    thread_dir = tmp_path / "thread"
    sub = thread_dir / "sub"
    sub.mkdir(parents=True)
    (sub / "book.epub").write_text("book")
    (sub / "audio.mp3").write_text("audio")

    files = scan_thread_dir(thread_dir, [])
    names = {Path(f).name for f in files}
    assert names == {"book.epub", "audio.mp3"}
