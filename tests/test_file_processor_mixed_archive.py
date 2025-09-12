from pathlib import Path
import shutil

from core.file_processor import FileProcessor


def test_handle_archive_preserves_audio_and_book(tmp_path, monkeypatch):
    download_dir = tmp_path / "dl"
    download_dir.mkdir()
    archive_path = download_dir / "input.rar"
    archive_path.write_bytes(b"orig")

    src = tmp_path / "src"
    src.mkdir()
    (src / "track1.mp3").write_text("a")
    (src / "book.epub").write_text("b")

    def fake_extract(self, archive, extract_dir, password=None):
        for f in src.iterdir():
            shutil.copy(f, extract_dir / f.name)
        return True
    monkeypatch.setattr(FileProcessor, "_extract_archive", fake_extract)

    def fake_rar(self, source_dir, output_base, root_name):
        out = output_base.with_suffix('.rar')
        with open(out, 'wb') as fh:
            fh.write(b'rar')
        return True
    monkeypatch.setattr(FileProcessor, "_create_rar_archive", fake_rar)

    fp = FileProcessor(download_dir=str(download_dir), winrar_path="/bin/true")
    fp.recompress_mode = "always"

    result = fp.handle_archive_file(archive_path, download_dir, "Thread Title")
    names = {Path(p).name for p in result}
    assert len(names) == 2
    assert any(n.endswith('.epub') for n in names)
    assert any(n.endswith('.rar') for n in names)
    # original archive should be removed
    assert not archive_path.exists()
