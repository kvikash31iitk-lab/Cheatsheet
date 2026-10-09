'use client';

import { useState, useRef, useEffect, DragEvent, ChangeEvent } from 'react';
import { AppBar } from '@/components/app-bar';
import {
  inspectDocument,
  getDemoDocument,
  generateDocumentCheatsheet,
  startBookBatchJob,
  getBookBatchStatus,
  stopBookBatchJob,
  type DocInspectionResult,
  type DocChapter,
  type BookBatchJob,
  getJob,
  type Job,
} from '@/lib/api';

export default function DocumentUploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [docInfo, setDocInfo] = useState<DocInspectionResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Mode selection: 'batch' (like playlist), 'single' (one chapter), 'custom' (page range)
  const [chapterMode, setChapterMode] = useState<'batch' | 'single' | 'custom'>('batch');

  // Single chapter selection
  const [selectedChapterIdx, setSelectedChapterIdx] = useState<number | ''>('');
  const [startPage, setStartPage] = useState<number>(1);
  const [endPage, setEndPage] = useState<number>(25);

  // Batch chapters selection
  const [selectedBatchChapterIndices, setSelectedBatchChapterIndices] = useState<Set<number>>(new Set());
  const [batchConcurrency, setBatchConcurrency] = useState<number>(2);

  // General options
  const [docTypeOverride, setDocTypeOverride] = useState<'auto' | 'digital' | 'scanned' | 'handwritten'>('auto');
  const [examTarget, setExamTarget] = useState('UPSC CSE GS & Optional');
  const [customTitle, setCustomTitle] = useState('');

  // Single generation state
  const [singleGenerating, setSingleGenerating] = useState(false);
  const [singleJobId, setSingleJobId] = useState<string | null>(null);
  const [singleJob, setSingleJob] = useState<Job | null>(null);
  const [showMarkdown, setShowMarkdown] = useState(false);

  // Batch generation state
  const [batchId, setBatchId] = useState<string | null>(null);
  const [batchJob, setBatchJob] = useState<BookBatchJob | null>(null);
  const [batchStarting, setBatchStarting] = useState(false);

  // Drag state
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isLocalHost, setIsLocalHost] = useState(false);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const h = window.location.hostname;
      setIsLocalHost(h === 'localhost' || h === '127.0.0.1');
    }
  }, []);

  // Handle Drag Events
  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      await handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleFileInputChange = async (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      await handleFileSelect(e.target.files[0]);
    }
  };

  const setupDefaultBatchSelection = (chapters: DocChapter[]) => {
    // Filter out obvious front/back matter (Copyright, Contents, Notes, Bibliography)
    const coreChapters = chapters.filter((c) => {
      const lower = c.title.toLowerCase();
      return !lower.startsWith('copyright') &&
             !lower.startsWith('contents') &&
             !lower.startsWith('preface') &&
             !lower.startsWith('acknowledgement') &&
             !lower.startsWith('notes') &&
             !lower.startsWith('select bibliography') &&
             !lower.startsWith('a note on style');
    });

    const targetList = coreChapters.length > 0 ? coreChapters : chapters;
    setSelectedBatchChapterIndices(new Set(targetList.map((c) => c.index)));
  };

  const handleFileSelect = async (selectedFile: File) => {
    setFile(selectedFile);
    setError(null);
    setSingleJobId(null);
    setSingleJob(null);
    setBatchId(null);
    setBatchJob(null);
    setInspecting(true);

    try {
      const res = await inspectDocument(selectedFile);
      setDocInfo(res);
      setCustomTitle(res.filename.replace(/\.[^/.]+$/, ''));
      setStartPage(1);
      setEndPage(Math.min(res.page_count, 25));

      if (res.chapters && res.chapters.length > 0) {
        setChapterMode('batch');
        setupDefaultBatchSelection(res.chapters);
        setSelectedChapterIdx(res.chapters[0].index);
        setStartPage(res.chapters[0].start_page);
        setEndPage(res.chapters[0].end_page);
      } else {
        setChapterMode('custom');
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to inspect uploaded document.');
    } finally {
      setInspecting(false);
    }
  };

  const handleLoadDemo = async () => {
    setError(null);
    setFile(null);
    setSingleJobId(null);
    setSingleJob(null);
    setBatchId(null);
    setBatchJob(null);
    setInspecting(true);

    try {
      const res = await getDemoDocument();
      setDocInfo(res);
      setCustomTitle('Bipan Chandra - India Since Independence');

      if (res.chapters && res.chapters.length > 0) {
        setChapterMode('batch');
        setupDefaultBatchSelection(res.chapters);
        const ch8 = res.chapters.find((c) => c.title.toLowerCase().includes('linguistic') || c.index === 12);
        if (ch8) {
          setSelectedChapterIdx(ch8.index);
          setStartPage(ch8.start_page);
          setEndPage(ch8.end_page);
        } else {
          setSelectedChapterIdx(res.chapters[0].index);
          setStartPage(res.chapters[0].start_page);
          setEndPage(res.chapters[0].end_page);
        }
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load demo document.');
    } finally {
      setInspecting(false);
    }
  };

  // Toggle single chapter checkbox in batch mode
  const toggleBatchChapter = (idx: number) => {
    setSelectedBatchChapterIndices((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const selectAllBatchChapters = () => {
    if (!docInfo?.chapters) return;
    setSelectedBatchChapterIndices(new Set(docInfo.chapters.map((c) => c.index)));
  };

  const selectCoreBatchChapters = () => {
    if (!docInfo?.chapters) return;
    setupDefaultBatchSelection(docInfo.chapters);
  };

  const deselectAllBatchChapters = () => {
    setSelectedBatchChapterIndices(new Set());
  };

  // Trigger Single Chapter Generation
  const handleStartSingleGeneration = async () => {
    if (!docInfo) return;
    setError(null);
    setSingleGenerating(true);

    try {
      const formData = new FormData();
      formData.append('file_id', docInfo.file_id);
      formData.append('doc_type', docTypeOverride === 'auto' ? docInfo.doc_type : docTypeOverride);
      formData.append('title', customTitle.trim());
      formData.append('exam_target', examTarget);

      let chapTitle = '';
      if (chapterMode === 'single' && selectedChapterIdx && docInfo.chapters) {
        const chap = docInfo.chapters.find((c) => c.index === selectedChapterIdx);
        if (chap) {
          chapTitle = chap.title;
          formData.append('chapter_title', chap.title);
          formData.append('start_page', String(chap.start_page));
          formData.append('end_page', String(chap.end_page));
        }
      } else {
        formData.append('start_page', String(startPage));
        formData.append('end_page', String(endPage));
      }

      const res = await generateDocumentCheatsheet(formData);
      setSingleJobId(res.id);
    } catch (err: any) {
      setError(err?.message || 'Could not start generation.');
      setSingleGenerating(false);
    }
  };

  // Trigger Batch Chapters Generation
  const handleStartBatchGeneration = async () => {
    if (!docInfo || !docInfo.chapters) return;
    const selectedChaptersList = docInfo.chapters.filter((c) => selectedBatchChapterIndices.has(c.index));
    if (selectedChaptersList.length === 0) {
      setError('Please select at least 1 chapter for batch processing.');
      return;
    }

    setError(null);
    setBatchStarting(true);

    try {
      const res = await startBookBatchJob({
        file_id: docInfo.file_id,
        book_title: customTitle.trim() || docInfo.filename,
        chapters: selectedChaptersList,
        concurrency: batchConcurrency,
        exam_target: examTarget,
      });

      setBatchId(res.batch_id);
      setBatchStarting(false);
    } catch (err: any) {
      setError(err?.message || 'Failed to start batch generation.');
      setBatchStarting(false);
    }
  };

  // Poll Single Job Progress
  useEffect(() => {
    if (!singleJobId) return;
    let cancelled = false;
    let timer: NodeJS.Timeout;

    const poll = async () => {
      try {
        const current = await getJob(singleJobId);
        if (cancelled) return;
        setSingleJob(current);

        if (current.status.state === 'done') {
          setSingleGenerating(false);
          return;
        }
        if (current.status.state === 'error') {
          setError(current.status.message || 'Generation failed.');
          setSingleGenerating(false);
          return;
        }

        timer = setTimeout(poll, 1500);
      } catch (e: any) {
        if (!cancelled) {
          timer = setTimeout(poll, 2500);
        }
      }
    };

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [singleJobId]);

  // Poll Batch Job Progress
  useEffect(() => {
    if (!batchId) return;
    let cancelled = false;
    let timer: NodeJS.Timeout;

    const pollBatch = async () => {
      try {
        const status = await getBookBatchStatus(batchId);
        if (cancelled) return;
        setBatchJob(status);

        if (status.status === 'complete' || status.status === 'stopped' || status.status === 'error') {
          return;
        }

        timer = setTimeout(pollBatch, 1500);
      } catch (e: any) {
        if (!cancelled) {
          timer = setTimeout(pollBatch, 2500);
        }
      }
    };

    pollBatch();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [batchId]);

  const handleStopBatch = async () => {
    if (!batchId) return;
    try {
      await stopBookBatchJob(batchId);
      const updated = await getBookBatchStatus(batchId);
      setBatchJob(updated);
    } catch (e) {
      // ignore
    }
  };

  return (
    <main style={{ minHeight: '100vh', background: 'var(--c-bg)', color: 'var(--c-ink)' }}>
      <AppBar />

      <div style={{ maxWidth: 940, margin: '0 auto', padding: '40px 24px' }}>
        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11.5,
              color: 'var(--c-ink-3)',
              letterSpacing: '.08em',
              marginBottom: 8,
              textTransform: 'uppercase',
            }}
          >
            Universal Ingestion Engine
          </div>
          <h1
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 40,
              fontWeight: 400,
              letterSpacing: '-0.02em',
              margin: '0 0 10px',
            }}
          >
            Books, PDFs & Handwritten Notes
          </h1>
          <p style={{ fontSize: 15, color: 'var(--c-ink-2)', margin: 0, lineHeight: 1.5 }}>
            Batch process entire textbooks chapter-by-chapter (like a video playlist), extract single chapters,
            or transcribe handwritten notes into publication-ready cheatsheets.
          </p>
        </div>

        {error && (
          <div
            style={{
              background: 'var(--c-error-bg)',
              color: 'var(--c-error)',
              padding: '12px 16px',
              borderRadius: 8,
              marginBottom: 20,
              fontSize: 14,
              border: '1px solid rgba(220, 38, 38, 0.2)',
            }}
          >
            ⚠️ {error}
          </div>
        )}

        {/* State 1: Dropzone */}
        {!docInfo && !inspecting && (
          <div>
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              style={{
                border: `2px dashed ${isDragging ? 'var(--c-accent)' : 'var(--c-line-2)'}`,
                borderRadius: 16,
                padding: '60px 24px',
                textAlign: 'center',
                background: isDragging ? 'var(--c-surface-2)' : 'var(--c-surface)',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
              }}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.webp"
                onChange={handleFileInputChange}
                style={{ display: 'none' }}
              />
              <div style={{ fontSize: 44, marginBottom: 12 }}>📁</div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
                Drop your PDF or image here, or browse
              </div>
              <div style={{ fontSize: 13.5, color: 'var(--c-ink-3)', marginBottom: 20 }}>
                Supports standard textbooks (.pdf), scanned Xerox handouts, and handwritten photos (.png, .jpg)
              </div>

              <div style={{ display: 'inline-flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center' }}>
                <span style={{ fontSize: 11.5, background: 'var(--c-surface-2)', padding: '4px 10px', borderRadius: 999, border: '1px solid var(--c-line)' }}>
                  🚀 Batch Chapter Processing (Like Playlist)
                </span>
                <span style={{ fontSize: 11.5, background: 'var(--c-surface-2)', padding: '4px 10px', borderRadius: 999, border: '1px solid var(--c-line)' }}>
                  📘 Auto Chapter Detection (TOC)
                </span>
                <span style={{ fontSize: 11.5, background: 'var(--c-surface-2)', padding: '4px 10px', borderRadius: 999, border: '1px solid var(--c-line)' }}>
                  ✍️ Multimodal Vision Handwriting OCR
                </span>
                <span style={{ fontSize: 11.5, background: 'var(--c-surface-2)', padding: '4px 10px', borderRadius: 999, border: '1px solid var(--c-line)' }}>
                  📄 100% Fact-Dense ReportLab PDF
                </span>
              </div>
            </div>

            {/* Quick Demo Button */}
            <div style={{ marginTop: 20, textAlign: 'center' }}>
              <span style={{ fontSize: 13, color: 'var(--c-ink-3)', marginRight: 12 }}>
                Want to test batch chapter processing right now?
              </span>
              <button
                type="button"
                onClick={handleLoadDemo}
                style={{
                  background: 'none',
                  border: '1px solid var(--c-line)',
                  borderRadius: 8,
                  padding: '6px 14px',
                  color: 'var(--c-accent)',
                  fontWeight: 600,
                  fontSize: 13,
                  cursor: 'pointer',
                }}
              >
                ⚡ Load Bipan Chandra (48 Chapters) Demo
              </button>
            </div>
          </div>
        )}

        {/* State 2: Inspecting Loading State */}
        {inspecting && (
          <div
            style={{
              padding: '60px 24px',
              textAlign: 'center',
              background: 'var(--c-surface)',
              borderRadius: 16,
              border: '1px solid var(--c-line)',
            }}
          >
            <div style={{ fontSize: 32, marginBottom: 12, animation: 'spin 1s infinite linear' }}>⏳</div>
            <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 6 }}>
              Pre-flight analyzing document...
            </div>
            <div style={{ fontSize: 13, color: 'var(--c-ink-3)' }}>
              Checking vector text density, embedded chapters (TOC), and page boundaries.
            </div>
          </div>
        )}

        {/* State 3: Document Config & Chapter Selector (when not actively in single or batch dashboard) */}
        {docInfo && !singleJobId && !batchId && (
          <div style={{ background: 'var(--c-surface)', borderRadius: 16, border: '1px solid var(--c-line)', padding: 28 }}>
            {/* Document Header Card */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                paddingBottom: 20,
                borderBottom: '1px solid var(--c-line)',
                marginBottom: 24,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                <div style={{ fontSize: 32 }}>
                  {docInfo.doc_type === 'handwritten' ? '✍️' : '📘'}
                </div>
                <div>
                  <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--c-ink)' }}>
                    {docInfo.filename}
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--c-ink-3)', marginTop: 2 }}>
                    {docInfo.page_count} pages · {docInfo.file_size_mb} MB ·{' '}
                    <span style={{ textTransform: 'capitalize', fontWeight: 500, color: 'var(--c-accent)' }}>
                      {docInfo.doc_type === 'digital' ? 'Vector Digital Book' : docInfo.doc_type === 'handwritten' ? 'Handwritten Notes' : 'Scanned Document'}
                    </span>
                  </div>
                </div>
              </div>

              <button
                type="button"
                onClick={() => { setDocInfo(null); setFile(null); }}
                style={{
                  background: 'none',
                  border: '1px solid var(--c-line)',
                  borderRadius: 6,
                  padding: '6px 12px',
                  fontSize: 12.5,
                  cursor: 'pointer',
                  color: 'var(--c-ink-2)',
                }}
              >
                Change File
              </button>
            </div>

            {/* Title override */}
            <div style={{ marginBottom: 20 }}>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                Cheatsheet Document Title
              </label>
              <input
                type="text"
                value={customTitle}
                onChange={(e) => setCustomTitle(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  borderRadius: 8,
                  border: '1px solid var(--c-line)',
                  background: 'var(--c-bg)',
                  color: 'var(--c-ink)',
                  fontSize: 14,
                }}
              />
            </div>

            {/* Chapter Mode Selector */}
            {docInfo.has_toc && docInfo.chapters.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
                  <button
                    type="button"
                    onClick={() => setChapterMode('batch')}
                    style={{
                      flex: 1.2,
                      padding: '10px 14px',
                      borderRadius: 8,
                      border: `1.5px solid ${chapterMode === 'batch' ? 'var(--c-accent)' : 'var(--c-line)'}`,
                      background: chapterMode === 'batch' ? 'var(--c-surface-2)' : 'transparent',
                      color: chapterMode === 'batch' ? 'var(--c-accent)' : 'var(--c-ink)',
                      fontWeight: chapterMode === 'batch' ? 700 : 400,
                      cursor: 'pointer',
                      fontSize: 13.5,
                    }}
                  >
                    🚀 Batch Process All Chapters ({docInfo.chapters.length} Found)
                  </button>
                  <button
                    type="button"
                    onClick={() => setChapterMode('single')}
                    style={{
                      flex: 1,
                      padding: '10px 14px',
                      borderRadius: 8,
                      border: `1.5px solid ${chapterMode === 'single' ? 'var(--c-accent)' : 'var(--c-line)'}`,
                      background: chapterMode === 'single' ? 'var(--c-surface-2)' : 'transparent',
                      fontWeight: chapterMode === 'single' ? 600 : 400,
                      cursor: 'pointer',
                      fontSize: 13.5,
                    }}
                  >
                    📑 Single Chapter
                  </button>
                  <button
                    type="button"
                    onClick={() => setChapterMode('custom')}
                    style={{
                      flex: 1,
                      padding: '10px 14px',
                      borderRadius: 8,
                      border: `1.5px solid ${chapterMode === 'custom' ? 'var(--c-accent)' : 'var(--c-line)'}`,
                      background: chapterMode === 'custom' ? 'var(--c-surface-2)' : 'transparent',
                      fontWeight: chapterMode === 'custom' ? 600 : 400,
                      cursor: 'pointer',
                      fontSize: 13.5,
                    }}
                  >
                    🔢 Custom Page Range
                  </button>
                </div>

                {/* Sub-View: BATCH MODE */}
                {chapterMode === 'batch' && (
                  <div
                    style={{
                      background: 'var(--c-bg)',
                      padding: 18,
                      borderRadius: 12,
                      border: '1px solid var(--c-line)',
                      marginBottom: 16,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                      <div>
                        <strong style={{ fontSize: 14 }}>Batch Chapter Queue</strong>
                        <span style={{ fontSize: 13, color: 'var(--c-ink-3)', marginLeft: 8 }}>
                          ({selectedBatchChapterIndices.size} of {docInfo.chapters.length} selected)
                        </span>
                      </div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button
                          type="button"
                          onClick={selectCoreBatchChapters}
                          style={{
                            fontSize: 12,
                            padding: '4px 10px',
                            borderRadius: 6,
                            background: 'var(--c-surface)',
                            border: '1px solid var(--c-line)',
                            cursor: 'pointer',
                            color: 'var(--c-accent)',
                            fontWeight: 600,
                          }}
                        >
                          Core Chapters Only
                        </button>
                        <button
                          type="button"
                          onClick={selectAllBatchChapters}
                          style={{
                            fontSize: 12,
                            padding: '4px 10px',
                            borderRadius: 6,
                            background: 'var(--c-surface)',
                            border: '1px solid var(--c-line)',
                            cursor: 'pointer',
                          }}
                        >
                          Select All
                        </button>
                        <button
                          type="button"
                          onClick={deselectAllBatchChapters}
                          style={{
                            fontSize: 12,
                            padding: '4px 10px',
                            borderRadius: 6,
                            background: 'var(--c-surface)',
                            border: '1px solid var(--c-line)',
                            cursor: 'pointer',
                            color: 'var(--c-ink-3)',
                          }}
                        >
                          Clear
                        </button>
                      </div>
                    </div>

                    {/* Checkbox list of chapters */}
                    <div
                      style={{
                        maxHeight: 280,
                        overflowY: 'auto',
                        border: '1px solid var(--c-line)',
                        borderRadius: 8,
                        background: 'var(--c-surface)',
                        padding: '6px 8px',
                      }}
                    >
                      {docInfo.chapters.map((chap) => {
                        const isChecked = selectedBatchChapterIndices.has(chap.index);
                        return (
                          <label
                            key={chap.index}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              padding: '8px 10px',
                              borderRadius: 6,
                              background: isChecked ? 'var(--c-surface-2)' : 'transparent',
                              cursor: 'pointer',
                              borderBottom: '1px solid var(--c-line)',
                              fontSize: 13,
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                              <input
                                type="checkbox"
                                checked={isChecked}
                                onChange={() => toggleBatchChapter(chap.index)}
                                style={{ cursor: 'pointer' }}
                              />
                              <span style={{ fontWeight: isChecked ? 600 : 400 }}>{chap.title}</span>
                            </div>
                            <span style={{ color: 'var(--c-ink-3)', fontSize: 12, fontFamily: 'var(--font-mono)' }}>
                              {chap.page_span}
                            </span>
                          </label>
                        );
                      })}
                    </div>

                    {/* Concurrency setting */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 14 }}>
                      <span style={{ fontSize: 13, color: 'var(--c-ink-2)' }}>
                        Parallel Workers (Concurrency):
                      </span>
                      <select
                        value={batchConcurrency}
                        onChange={(e) => setBatchConcurrency(parseInt(e.target.value) || 2)}
                        style={{
                          padding: '4px 10px',
                          borderRadius: 6,
                          border: '1px solid var(--c-line)',
                          background: 'var(--c-surface)',
                          color: 'var(--c-ink)',
                          fontSize: 13,
                        }}
                      >
                        <option value="1">1 chapter at a time</option>
                        <option value="2">2 chapters in parallel (Recommended)</option>
                        <option value="3">3 chapters in parallel (Fastest)</option>
                      </select>
                    </div>
                  </div>
                )}

                {/* Sub-View: SINGLE CHAPTER */}
                {chapterMode === 'single' && (
                  <div style={{ marginBottom: 16 }}>
                    <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                      Select Target Chapter
                    </label>
                    <select
                      value={selectedChapterIdx}
                      onChange={(e) => {
                        const idx = parseInt(e.target.value, 10);
                        setSelectedChapterIdx(idx);
                        const c = docInfo.chapters.find((ch) => ch.index === idx);
                        if (c) {
                          setStartPage(c.start_page);
                          setEndPage(c.end_page);
                        }
                      }}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        borderRadius: 8,
                        border: '1px solid var(--c-line)',
                        background: 'var(--c-bg)',
                        color: 'var(--c-ink)',
                        fontSize: 14,
                      }}
                    >
                      {docInfo.chapters.map((chap) => (
                        <option key={chap.index} value={chap.index}>
                          {chap.title} ({chap.page_span})
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {/* Sub-View: CUSTOM RANGE */}
                {chapterMode === 'custom' && (
                  <div style={{ display: 'flex', gap: 14, marginBottom: 16 }}>
                    <div style={{ flex: 1 }}>
                      <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                        Start Page
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={docInfo.page_count}
                        value={startPage}
                        onChange={(e) => setStartPage(Math.max(1, parseInt(e.target.value) || 1))}
                        style={{
                          width: '100%',
                          padding: '10px 12px',
                          borderRadius: 8,
                          border: '1px solid var(--c-line)',
                          background: 'var(--c-bg)',
                          color: 'var(--c-ink)',
                          fontSize: 14,
                        }}
                      />
                    </div>
                    <div style={{ flex: 1 }}>
                      <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                        End Page
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={docInfo.page_count}
                        value={endPage}
                        onChange={(e) => setEndPage(Math.min(docInfo.page_count, parseInt(e.target.value) || 1))}
                        style={{
                          width: '100%',
                          padding: '10px 12px',
                          borderRadius: 8,
                          border: '1px solid var(--c-line)',
                          background: 'var(--c-bg)',
                          color: 'var(--c-ink)',
                          fontSize: 14,
                        }}
                      />
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* If no TOC found */}
            {(!docInfo.has_toc || docInfo.chapters.length === 0) && (
              <div style={{ marginBottom: 20 }}>
                <div style={{ display: 'flex', gap: 14 }}>
                  <div style={{ flex: 1 }}>
                    <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                      Start Page
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={docInfo.page_count}
                      value={startPage}
                      onChange={(e) => setStartPage(Math.max(1, parseInt(e.target.value) || 1))}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        borderRadius: 8,
                        border: '1px solid var(--c-line)',
                        background: 'var(--c-bg)',
                        color: 'var(--c-ink)',
                        fontSize: 14,
                      }}
                    />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                      End Page (Max 15 pages for vision)
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={docInfo.page_count}
                      value={endPage}
                      onChange={(e) => setEndPage(Math.min(docInfo.page_count, parseInt(e.target.value) || 1))}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        borderRadius: 8,
                        border: '1px solid var(--c-line)',
                        background: 'var(--c-bg)',
                        color: 'var(--c-ink)',
                        fontSize: 14,
                      }}
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Ingestion & Target Exam options */}
            <div style={{ display: 'flex', gap: 14, marginBottom: 24 }}>
              <div style={{ flex: 1 }}>
                <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                  Ingestion Mode
                </label>
                <select
                  value={docTypeOverride}
                  onChange={(e) => setDocTypeOverride(e.target.value as any)}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    borderRadius: 8,
                    border: '1px solid var(--c-line)',
                    background: 'var(--c-bg)',
                    color: 'var(--c-ink)',
                    fontSize: 13.5,
                  }}
                >
                  <option value="auto">Auto-Detect ({docInfo.doc_type})</option>
                  <option value="digital">Force Vector Text Slicing</option>
                  <option value="handwritten">Force Gemini Multimodal Vision (Handwriting / Diagrams)</option>
                </select>
              </div>

              <div style={{ flex: 1 }}>
                <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                  Target Exam Focus
                </label>
                <select
                  value={examTarget}
                  onChange={(e) => setExamTarget(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    borderRadius: 8,
                    border: '1px solid var(--c-line)',
                    background: 'var(--c-bg)',
                    color: 'var(--c-ink)',
                    fontSize: 13.5,
                  }}
                >
                  <option value="UPSC CSE GS & Optional">UPSC CSE GS & Optional</option>
                  <option value="State PCS (UPPSC, BPSC, RAS, MPPSC)">State PCS Examination</option>
                  <option value="General Competitive & University">General Competitive / Academic</option>
                </select>
              </div>
            </div>

            {/* Launch Buttons based on mode */}
            {chapterMode === 'batch' ? (
              <button
                type="button"
                onClick={handleStartBatchGeneration}
                disabled={batchStarting || selectedBatchChapterIndices.size === 0}
                style={{
                  width: '100%',
                  padding: '14px 20px',
                  borderRadius: 999,
                  background: 'var(--c-accent)',
                  color: '#fff',
                  fontSize: 16,
                  fontWeight: 600,
                  border: 'none',
                  cursor: selectedBatchChapterIndices.size === 0 ? 'not-allowed' : 'pointer',
                  opacity: selectedBatchChapterIndices.size === 0 ? 0.6 : 1,
                }}
              >
                🚀 Batch Process {selectedBatchChapterIndices.size} Chapters (Like Playlist Queue)
              </button>
            ) : (
              <button
                type="button"
                onClick={handleStartSingleGeneration}
                disabled={singleGenerating}
                style={{
                  width: '100%',
                  padding: '14px 20px',
                  borderRadius: 999,
                  background: 'var(--c-accent)',
                  color: '#fff',
                  fontSize: 16,
                  fontWeight: 600,
                  border: 'none',
                  cursor: 'pointer',
                }}
              >
                ⚡ Generate Cheatsheet ({chapterMode === 'single' ? 'Single Chapter' : `Pages ${startPage}–${endPage}`})
              </button>
            )}
          </div>
        )}

        {/* State 4: BATCH DASHBOARD (LIVE REAL-TIME PROGRESS LIKE PLAYLIST) */}
        {batchId && (
          <div
            style={{
              background: 'var(--c-surface)',
              borderRadius: 16,
              border: '1px solid var(--c-line)',
              padding: 28,
            }}
          >
            {/* Batch Header & Progress */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
              <div>
                <div style={{ fontSize: 12, textTransform: 'uppercase', color: 'var(--c-accent)', fontWeight: 700, letterSpacing: '.05em', marginBottom: 4 }}>
                  Batch Book Generation · {batchJob?.status === 'complete' ? 'Completed' : batchJob?.status === 'stopped' ? 'Stopped' : 'In Progress'}
                </div>
                <h2 style={{ fontSize: 24, fontWeight: 600, margin: '0 0 6px', color: 'var(--c-ink)' }}>
                  {batchJob?.book_title || customTitle}
                </h2>
                <div style={{ fontSize: 13.5, color: 'var(--c-ink-3)' }}>
                  {batchJob ? `${batchJob.completed_count} of ${batchJob.total_chapters} Chapters Completed` : 'Initializing batch...'}
                </div>
              </div>

              {/* Action Buttons */}
              <div style={{ display: 'flex', gap: 10 }}>
                {batchJob && batchJob.completed_count > 0 && (
                  <a
                    href={`/api/docs/batch/download-all/${batchId}`}
                    download
                    style={{
                      padding: '8px 16px',
                      borderRadius: 999,
                      background: 'var(--c-accent)',
                      color: '#fff',
                      fontSize: 13,
                      fontWeight: 600,
                      textDecoration: 'none',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                    }}
                  >
                    📦 Download All ({batchJob.completed_count}) as ZIP
                  </a>
                )}

                {batchJob?.status === 'running' && (
                  <button
                    type="button"
                    onClick={handleStopBatch}
                    style={{
                      padding: '8px 14px',
                      borderRadius: 999,
                      border: '1px solid var(--c-line)',
                      background: 'var(--c-surface-2)',
                      color: 'var(--c-error)',
                      fontSize: 13,
                      cursor: 'pointer',
                      fontWeight: 500,
                    }}
                  >
                    ⏹️ Stop Batch
                  </button>
                )}

                <button
                  type="button"
                  onClick={() => {
                    setBatchId(null);
                    setBatchJob(null);
                    setDocInfo(null);
                    setFile(null);
                  }}
                  style={{
                    padding: '8px 14px',
                    borderRadius: 999,
                    border: '1px solid var(--c-line)',
                    background: 'none',
                    color: 'var(--c-ink-2)',
                    fontSize: 13,
                    cursor: 'pointer',
                  }}
                >
                  + New Book / Notes
                </button>
              </div>
            </div>

            {/* Overall Progress Bar */}
            {batchJob && (
              <div style={{ marginBottom: 24 }}>
                <div
                  style={{
                    width: '100%',
                    height: 10,
                    background: 'var(--c-line)',
                    borderRadius: 999,
                    overflow: 'hidden',
                    marginBottom: 8,
                  }}
                >
                  <div
                    style={{
                      height: '100%',
                      width: `${Math.round((batchJob.completed_count / Math.max(1, batchJob.total_chapters)) * 100)}%`,
                      background: batchJob.status === 'complete' ? '#10b981' : 'var(--c-accent)',
                      transition: 'width 0.4s ease',
                    }}
                  />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, color: 'var(--c-ink-3)' }}>
                  <span>
                    ✓ {batchJob.completed_count} Done · ⏳ {batchJob.total_chapters - batchJob.completed_count - batchJob.failed_count} Pending
                    {batchJob.failed_count > 0 && ` · ⚠️ ${batchJob.failed_count} Failed`}
                  </span>
                  <span style={{ fontFamily: 'var(--font-mono)' }}>
                    {Math.round((batchJob.completed_count / Math.max(1, batchJob.total_chapters)) * 100)}%
                  </span>
                </div>
              </div>
            )}

            {/* Desktop Notification Card */}
            <div
              style={{
                fontSize: 12.5,
                color: 'var(--c-ink-2)',
                background: 'var(--c-bg)',
                padding: '10px 14px',
                borderRadius: 8,
                marginBottom: 20,
                border: '1px solid var(--c-line)',
              }}
            >
              💻 <strong>Auto-Saved to Desktop:</strong> Chapter PDFs are being saved live to{' '}
              <code style={{ color: 'var(--c-accent)' }}>
                {batchJob?.desktop_folder || `Desktop\\Civils Tap\\${customTitle}`}
              </code>
            </div>

            {/* Chapter Items List */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {batchJob?.items &&
                Object.values(batchJob.items).map((item) => (
                  <div
                    key={item.index}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '12px 16px',
                      borderRadius: 10,
                      background: 'var(--c-bg)',
                      border: `1px solid ${
                        item.status === 'complete'
                          ? 'rgba(16, 185, 129, 0.3)'
                          : item.status === 'running'
                          ? 'rgba(59, 130, 246, 0.4)'
                          : 'var(--c-line)'
                      }`,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                      <span
                        style={{
                          width: 28,
                          height: 28,
                          borderRadius: '50%',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: 12,
                          fontWeight: 700,
                          background:
                            item.status === 'complete'
                              ? 'rgba(16, 185, 129, 0.15)'
                              : item.status === 'running'
                              ? 'rgba(59, 130, 246, 0.15)'
                              : 'var(--c-surface)',
                          color:
                            item.status === 'complete'
                              ? '#10b981'
                              : item.status === 'running'
                              ? '#3b82f6'
                              : 'var(--c-ink-3)',
                        }}
                      >
                        {item.status === 'complete' ? '✓' : item.index}
                      </span>
                      <div>
                        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--c-ink)' }}>
                          {item.title}
                        </div>
                        <div style={{ fontSize: 12, color: 'var(--c-ink-3)', marginTop: 2 }}>
                          {item.page_span} ·{' '}
                          <span
                            style={{
                              color:
                                item.status === 'complete'
                                  ? '#10b981'
                                  : item.status === 'running'
                                  ? '#3b82f6'
                                  : 'var(--c-ink-3)',
                              fontWeight: 500,
                            }}
                          >
                            {item.step || item.status}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Chapter Download Button */}
                    <div>
                      {item.status === 'complete' && item.pdf_url ? (
                        <a
                          href={item.pdf_url}
                          download
                          style={{
                            padding: '6px 14px',
                            borderRadius: 999,
                            background: 'var(--c-surface)',
                            border: '1px solid var(--c-line)',
                            color: 'var(--c-accent)',
                            fontWeight: 600,
                            fontSize: 12.5,
                            textDecoration: 'none',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                          }}
                        >
                          📥 Download PDF
                        </a>
                      ) : item.status === 'running' ? (
                        <span style={{ fontSize: 12.5, color: '#3b82f6', fontWeight: 500 }}>
                          ⚡ Processing...
                        </span>
                      ) : (
                        <span style={{ fontSize: 12.5, color: 'var(--c-ink-3)' }}>⏳ Queued</span>
                      )}
                    </div>
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* State 5: Single Generation Live Progress Bar */}
        {singleJobId && singleGenerating && (
          <div
            style={{
              background: 'var(--c-surface)',
              borderRadius: 16,
              border: '1px solid var(--c-line)',
              padding: 32,
              textAlign: 'center',
            }}
          >
            <div style={{ fontSize: 32, marginBottom: 12 }}>⚡</div>
            <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
              {singleJob?.status.state === 'running' ? (singleJob.status as any).step : 'Starting pipeline...'}
            </div>
            <div style={{ fontSize: 13.5, color: 'var(--c-ink-3)', marginBottom: 24 }}>
              Extracting facts, synthesizing comparative matrices & compiling ReportLab PDF.
            </div>

            <div
              style={{
                width: '100%',
                height: 8,
                background: 'var(--c-line)',
                borderRadius: 999,
                overflow: 'hidden',
                marginBottom: 12,
              }}
            >
              <div
                style={{
                  height: '100%',
                  width: `${Math.round(((singleJob?.status as any)?.progress || 0.1) * 100)}%`,
                  background: 'var(--c-accent)',
                  transition: 'width 0.4s ease',
                }}
              />
            </div>

            <div style={{ fontSize: 13, color: 'var(--c-ink-3)', fontFamily: 'var(--font-mono)' }}>
              {Math.round(((singleJob?.status as any)?.progress || 0.1) * 100)}% Complete
            </div>
          </div>
        )}

        {/* State 6: Single Done Screen */}
        {singleJobId && singleJob?.status.state === 'done' && (
          <div
            style={{
              background: 'var(--c-surface)',
              borderRadius: 16,
              border: '1px solid rgba(16, 185, 129, 0.3)',
              padding: 32,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 20 }}>
              <div
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: '50%',
                  background: 'rgba(16, 185, 129, 0.15)',
                  color: '#10b981',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 22,
                }}
              >
                ✓
              </div>
              <div>
                <div style={{ fontSize: 20, fontWeight: 600, color: 'var(--c-ink)' }}>
                  Cheatsheet Ready!
                </div>
                <div style={{ fontSize: 13.5, color: 'var(--c-ink-3)' }}>
                  {singleJob.meta?.title || customTitle}
                </div>
              </div>
            </div>

            {(() => {
              const pdfUrl = (singleJob.status as any).pdf_url || `/api/files/${singleJobId}/pdf`;
              const safeDownloadName = `${(singleJob.meta?.title || customTitle || 'Cheatsheet').replace(/[^\w\s.-]/g, '_').trim()}.pdf`;
              return (
                <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
                  <a
                    href={pdfUrl}
                    download={safeDownloadName}
                    style={{
                      flex: 1,
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 8,
                      padding: '12px 20px',
                      borderRadius: 999,
                      background: 'var(--c-accent)',
                      color: '#fff',
                      fontWeight: 600,
                      fontSize: 15,
                      textDecoration: 'none',
                    }}
                  >
                    📥 Download Publication PDF
                  </a>

                  <a
                    href={`${pdfUrl}?inline=1`}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      padding: '12px 20px',
                      borderRadius: 999,
                      border: '1px solid var(--c-line)',
                      background: 'var(--c-surface-2)',
                      color: 'var(--c-ink)',
                      fontWeight: 600,
                      fontSize: 15,
                      textDecoration: 'none',
                      display: 'inline-flex',
                      alignItems: 'center',
                    }}
                  >
                    👁️ View PDF
                  </a>
                </div>
              );
            })()}

            {isLocalHost ? (
              <div
                style={{
                  fontSize: 12.5,
                  color: 'var(--c-ink-3)',
                  background: 'var(--c-bg)',
                  padding: '10px 14px',
                  borderRadius: 8,
                  marginBottom: 20,
                  border: '1px solid var(--c-line)',
                }}
              >
                💻 <strong>Desktop copy saved:</strong> Automatically copied to{' '}
                <code style={{ color: 'var(--c-accent)' }}>Desktop\Civils Tap\Documents</code> for offline access.
              </div>
            ) : (
              <div
                style={{
                  fontSize: 12.5,
                  color: 'var(--c-ink-3)',
                  background: 'var(--c-bg)',
                  padding: '10px 14px',
                  borderRadius: 8,
                  marginBottom: 20,
                  border: '1px solid var(--c-line)',
                }}
              >
                ✨ <strong>Publication PDF Ready:</strong> Complete with high-density revision matrices, chronological timelines, fact grids, and exam traps.
              </div>
            )}

            <div style={{ borderTop: '1px solid var(--c-line)', paddingTop: 18 }}>
              <button
                type="button"
                onClick={() => setShowMarkdown(!showMarkdown)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--c-ink-2)',
                  cursor: 'pointer',
                  fontSize: 13,
                  fontWeight: 500,
                  padding: 0,
                  textDecoration: 'underline',
                }}
              >
                {showMarkdown ? 'Hide Raw Markdown' : 'Preview / Copy Markdown Content'}
              </button>

              {showMarkdown && (
                <div style={{ marginTop: 14 }}>
                  <pre
                    style={{
                      background: 'var(--c-bg)',
                      padding: 16,
                      borderRadius: 8,
                      maxHeight: 360,
                      overflowY: 'auto',
                      fontSize: 12.5,
                      lineHeight: 1.5,
                      whiteSpace: 'pre-wrap',
                      border: '1px solid var(--c-line)',
                    }}
                  >
                    {(singleJob.status as any).markdown}
                  </pre>
                </div>
              )}
            </div>

            <div style={{ marginTop: 20, textAlign: 'center' }}>
              <button
                type="button"
                onClick={() => {
                  setSingleJobId(null);
                  setSingleJob(null);
                  setDocInfo(null);
                  setFile(null);
                }}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--c-accent)',
                  cursor: 'pointer',
                  fontSize: 13.5,
                  fontWeight: 600,
                }}
              >
                + Process Another Chapter or Book
              </button>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
