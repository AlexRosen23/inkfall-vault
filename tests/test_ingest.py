import pytest

from inkfall.ingest import IngestError, chunk_spans, normalize_text, sentence_spans, sniff_and_extract


def test_chunk_offsets_match_source_for_every_seed_doc(corpus):
    for d in corpus:
        body = normalize_text(d.body)
        spans = chunk_spans(body)
        assert spans, d.ref
        for s in spans:
            assert body[s.start:s.end].strip() == body[s.start:s.end], d.ref
            assert 0 < s.end - s.start <= 900
            for a, b in sentence_spans(body, s.start, s.end):
                assert s.start <= a < b <= s.end


def test_stored_chunks_match_immutable_version_text(base_db):
    from sqlalchemy import select

    from inkfall.db import Chunk, make_engine, session_factory
    with session_factory(make_engine(base_db))() as s:
        for c in s.scalars(select(Chunk)):
            assert c.version.text[c.char_start:c.char_end] == c.text


@pytest.mark.parametrize("name,data,reason", [
    ("empty.txt", b"", "empty"),
    ("big.txt", b"a" * (2 * 1024 * 1024 + 1), "exceeds"),
    ("tool.exe", b"MZ\x90\x00", "unsupported"),
    ("notes.txt", b"\xff\xfe\x00bad", "UTF-8"),
    ("fake.pdf", b"hello, not a pdf", "%PDF-"),
    ("broken.pdf", b"%PDF-1.7\n1 0 obj << /Type /Catalog >> garbage", "PDF"),
    ("sneaky.txt", b"%PDF-1.4 binary", "binary"),
    ("archive.md", b"PK\x03\x04zipdata", "binary"),
    ("noext", b"plain text", "unsupported"),
])
def test_unsafe_uploads_rejected(name, data, reason):
    with pytest.raises(IngestError) as exc:
        sniff_and_extract(name, data)
    assert reason.lower() in str(exc.value).lower()


def test_text_upload_normalized_and_control_chars_stripped():
    text, mime, method = sniff_and_extract("memo.md", b"# Memo\r\n\r\nLine\x07 one.\r\n")
    assert "\r" not in text and "\x07" not in text and mime == "text/markdown" and "utf-8" in method


def test_pdf_text_layer_extracted():
    pypdf = pytest.importorskip("pypdf")
    from io import BytesIO
    w = pypdf.PdfWriter()
    w.add_blank_page(200, 200)
    buf = BytesIO()
    w.write(buf)
    with pytest.raises(IngestError, match="no extractable text"):
        sniff_and_extract("scan.pdf", buf.getvalue())
