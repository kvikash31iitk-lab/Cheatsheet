import os
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / 'version.json'

if VERSION_FILE.exists():
    v_info = json.loads(VERSION_FILE.read_text(encoding='utf-8'))
    version = v_info.get('version', '2.1.0')
else:
    version = '2.1.0'

print(f'=== Packaging Cheatsheet Desktop Release v{version} ===')

PUBLIC_DOWNLOADS = ROOT / 'web' / 'public' / 'downloads'
PUBLIC_DOWNLOADS.mkdir(parents=True, exist_ok=True)

OUT_ZIP_LATEST = PUBLIC_DOWNLOADS / 'Cheatsheet_Desktop_Latest.zip'
OUT_ZIP_VERSIONED = PUBLIC_DOWNLOADS / f'Cheatsheet_Desktop_v{version}.zip'

EXCLUDE_DIRS = {
    '.git', '.venv', 'venv', 'node_modules', '.next', '__pycache__',
    'web_work', '.upsc_work', 'work', 'tmp', '.system_generated',
    '.tempmediaStorage', '.user_uploaded', 'scratch', 'local-runs', 'agent-work'
}

EXCLUDE_EXTENSIONS = {
    '.pyc', '.pyo', '.pyd', '.log', '.DS_Store', '.mp4', '.mp3', '.m4a', '.webm'
}

# Temporary zip build
temp_zip = ROOT / 'Cheatsheet_temp.zip'
if temp_zip.exists():
    temp_zip.unlink()

with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.next') and d != 'downloads']
        
        for f in files:
            p = Path(root) / f
            ext = p.suffix.lower()
            if ext in EXCLUDE_EXTENSIONS:
                continue
            if p.name in ('.env.local', 'Cheatsheet_temp.zip', 'Cheatsheet_Plug_And_Play_Home_PC.zip'):
                continue
            
            rel_path = p.relative_to(ROOT)
            zf.write(p, arcname=str(rel_path))

# Copy to web public downloads for website download button
shutil.copy(temp_zip, OUT_ZIP_LATEST)
shutil.copy(temp_zip, OUT_ZIP_VERSIONED)

temp_zip.unlink()

size_mb = OUT_ZIP_LATEST.stat().st_size / (1024 * 1024)
print(f'[SUCCESS] Created {OUT_ZIP_LATEST.name} ({size_mb:.2f} MB)')
print(f'[SUCCESS] Created {OUT_ZIP_VERSIONED.name}')
