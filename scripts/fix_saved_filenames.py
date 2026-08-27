import re
import json
import shutil
import zipfile
import pathlib

ROOT = pathlib.Path(".")
SAVED_DIR = ROOT / "saved files"
SAVED_DIR.mkdir(parents=True, exist_ok=True)

def clean_video_title(raw_title: str) -> str:
    """Extract a clean, human-readable topic name from raw YouTube titles."""
    if not raw_title or raw_title.startswith("http"):
        return "Lecture Note"
    
    t = raw_title
    # Strip emojis and non-ascii
    t = re.sub(r'[^\x00-\x7F]+', ' ', t)
    # Remove leading numbering like '26 '
    t = re.sub(r'^\d+\s+', '', t)
    # Remove common prefix boilerplates
    t = re.sub(r'^UPSC\s+EPFO\s+(?:AO/?EO\s*(?:&|and)?\s*)?(?:APFC\s*)?\|\s*', '', t, flags=re.I)
    t = re.sub(r'^General Accounting Principles\s*\|\s*', '', t, flags=re.I)
    t = re.sub(r'^EPFO Complete Course\s*\|\s*', '', t, flags=re.I)
    # Remove trailing teacher / channel tags
    t = re.sub(r'\|\s*(?:By\s+)?(?:Anurag\s*Sir|EPFO Exam Preparation|EduTap|Civilstap|Anuj Jindal|MBA Pathshala|MBA Wallah|Vijay Sir|Smriti Shah|Raj Shamani).*$', '', t, flags=re.I)
    t = re.sub(r'[\\/*?:"<>|\r\n\t]', '_', t)
    t = re.sub(r'_+', '_', t).strip(' _.-|')
    return t if t else raw_title[:60]

# 1. Clean and rebuild the 30-module General Accounting playlist ZIP
job_dir = ROOT / "web_work" / "playlist_jobs" / "fc6e10e5db4f4ebb98b57ae14cf12125"
if job_dir.exists():
    modules = []
    for sub in sorted(job_dir.iterdir()):
        if sub.is_dir() and sub.name != "Consolidated":
            src_f = list(sub.glob("**/source.json"))
            pdf_f = list(sub.glob("**/cheatsheet.pdf"))
            md_f = list(sub.glob("**/cheatsheet.md"))
            
            raw_title = sub.name
            vid_id = sub.name.split('_', 1)[1] if '_' in sub.name else sub.name
            if src_f:
                try:
                    s_data = json.loads(src_f[0].read_text(encoding="utf-8"))
                    raw_title = s_data.get("title") or raw_title
                except Exception:
                    pass
            elif md_f:
                first_line = md_f[0].read_text(encoding="utf-8").splitlines()[0]
                raw_title = first_line.lstrip('# ')
                
            clean_t = clean_video_title(raw_title)
            if pdf_f and md_f:
                modules.append({
                    "sub_name": sub.name,
                    "raw_title": raw_title,
                    "clean_title": clean_t,
                    "pdf_path": pdf_f[0],
                    "md_path": md_f[0],
                })
    
    def extract_class_num(m):
        match = re.search(r'(?:Class|Lec|Part)[-\s:]*(\d+)', m["raw_title"], re.I)
        return int(match.group(1)) if match else 99
    
    modules.sort(key=extract_class_num)
    
    course_zip_name = "UPSC EPFO APFC - General Accounting Principles (30 Modules) - Playlist.zip"
    course_zip_path = SAVED_DIR / course_zip_name
    
    master_pdf = job_dir / "Consolidated" / "master_cheatsheet.pdf"
    
    with zipfile.ZipFile(course_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if master_pdf.is_file():
            zf.write(master_pdf, arcname="00_Master_Consolidated_Course_Handbook.pdf")
        for idx, mod in enumerate(modules, start=1):
            clean_file_name = f"{idx:02d}. {mod['clean_title']} - Cheatsheet.pdf"
            zf.write(mod["pdf_path"], arcname=f"Individual_Modules/{clean_file_name}")
            
    # Save Master Handbook with clean name
    master_dest_pdf = SAVED_DIR / "UPSC EPFO APFC - General Accounting Principles (30 Modules) - Master Handbook.pdf"
    master_dest_md = SAVED_DIR / "UPSC EPFO APFC - General Accounting Principles (30 Modules) - Master Handbook.md"
    if master_pdf.is_file():
        shutil.copy2(master_pdf, master_dest_pdf)
    master_md = job_dir / "Consolidated" / "master_cheatsheet.md"
    if master_md.is_file():
        shutil.copy2(master_md, master_dest_md)

# 2. Clean up old raw video-id files in 'saved files'
for old_f in SAVED_DIR.glob("*"):
    if re.match(r'^(?:0TltdI6D_6U|4tI-h-GKWVk|dbrMiuqbCXQ|ZTWSHhg2-Mk|D3sHmhyotxw|General Science Complete Course 30 Modules).*', old_f.name):
        try:
            old_f.unlink()
        except Exception:
            pass

# 3. Re-save local-runs with their real video titles
local_runs = ROOT / "data" / "local-runs"
for vdir in local_runs.iterdir():
    if vdir.is_dir():
        vid = vdir.name
        title = vid
        meta_f = vdir / "meta.json"
        src_f = vdir / "source.json"
        if meta_f.is_file():
            try:
                title = json.loads(meta_f.read_text(encoding="utf-8")).get("title") or title
            except Exception:
                pass
        elif src_f.is_file():
            try:
                title = json.loads(src_f.read_text(encoding="utf-8")).get("title") or title
            except Exception:
                pass
        else:
            for md_f in vdir.glob("*.md"):
                first_l = md_f.read_text(encoding="utf-8").splitlines()[0]
                if first_l.startswith("# "):
                    title = first_l.lstrip("# ")
                    break
                    
        clean_t = clean_video_title(title)
        for k in ["cheatsheet", "mcq", "book"]:
            p = vdir / f"{k}.pdf"
            m = vdir / f"{k}.md"
            label = "Cheatsheet" if k == "cheatsheet" else ("Solved MCQs" if k == "mcq" else "Illustrated Book")
            if p.is_file():
                dest_p = SAVED_DIR / f"{clean_t} - {label}.pdf"
                shutil.copy2(p, dest_p)
            if m.is_file():
                dest_m = SAVED_DIR / f"{clean_t} - {label}.md"
                shutil.copy2(m, dest_m)

print("SUCCESS: All files and ZIP packages in 'saved files' updated with clean human-readable names!")
