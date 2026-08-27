import sys
import pathlib
import sqlite3
import json

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.file_saver import save_generated_artifacts

# 1. Check data/local-runs
runs_dir = ROOT / "data" / "local-runs"
if runs_dir.is_dir():
    for vdir in runs_dir.iterdir():
        if vdir.is_dir():
            for k in ["cheatsheet", "mcq", "book"]:
                pdf = vdir / f"{k}.pdf"
                md = vdir / f"{k}.md"
                if pdf.is_file():
                    title = vdir.name
                    meta_f = vdir / "meta.json"
                    if meta_f.is_file():
                        try:
                            meta = json.loads(meta_f.read_text(encoding="utf-8"))
                            title = meta.get("title") or title
                        except Exception:
                            pass
                    save_generated_artifacts(pdf_path=pdf, md_path=md, title=title, kind=k)

# 2. Check web_work app.db
db_path = ROOT / "web_work" / "app.db"
if db_path.is_file():
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, title, kind, pdf_path FROM generations WHERE status='done'")
        for jid, title, kind, pdf_path in cur.fetchall():
            p = pathlib.Path(pdf_path) if pdf_path else None
            m = ROOT / "web_work" / jid / "output.md"
            if p and p.is_file():
                save_generated_artifacts(pdf_path=p, md_path=m if m.is_file() else None, title=title or jid, kind=kind or "cheatsheet")
    except Exception as exc:
        print("db scan note:", exc)
