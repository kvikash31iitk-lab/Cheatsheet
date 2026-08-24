# 🚀 Cheatsheet AI - Plug & Play Package (Home PC Edition)

This is the complete, self-contained standalone version of **Cheatsheet AI** with full support for:
- 📝 Video Note & Cheatsheet Generation
- 📚 Illustrated Book Handbooks
- 🎯 Solved MCQ / PYQ Handbooks (with 12/12 question guarantees)
- 📐 Native Vector Geometric Diagrams & Seating Arrangements
- 🧪 Chemistry Reaction & Math Subscript Sanitization
- 🌐 Automatic Default Browser UI

---

## ⚡ Quick 3-Step Setup on Any Windows PC:

### Step 1: Requirements
Make sure you have:
1. **Python 3.10+** installed ([Download from python.org](https://www.python.org/downloads/)) — *Check "Add Python to PATH" during installation.*
2. **Node.js 18+** installed ([Download from nodejs.org](https://nodejs.org/)) — *(Optional, for the local web UI).*

---

### Step 2: Configure API Keys
Open `.env` in Notepad and insert your free Google Gemini or Groq API keys:
```env
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
```

---

### Step 3: Launch
Double-click **`START_CHEATSHEET.bat`**!
* It automatically configures dependencies, starts the local engine, and pops open your default web browser at `http://localhost:3000/generate`.

---

## 🛠️ Offline CLI / Command Line Generation:

You can also generate handbooks directly from PowerShell or Command Prompt:

```bash
# Generate Solved MCQ Handbook
python scripts/run_local_job.py "https://www.youtube.com/watch?v=VIDEO_ID" --kind mcq

# Generate Visual Cheatsheet
python scripts/run_local_job.py "https://www.youtube.com/watch?v=VIDEO_ID" --kind cheatsheet

# Generate Illustrated Book
python scripts/run_local_job.py "https://www.youtube.com/watch?v=VIDEO_ID" --kind book
```
