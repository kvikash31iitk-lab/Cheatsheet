'use client';

import * as React from 'react';
import { Btn, Tag } from './ui';
import { Ic } from './icons';

interface DesktopDownloadModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function DesktopDownloadModal({ isOpen, onClose }: DesktopDownloadModalProps) {
  const [password, setPassword] = React.useState('');
  const [error, setError] = React.useState('');
  const [downloading, setDownloading] = React.useState(false);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const clean = password.trim();
    if (clean.toLowerCase() !== 'sristy') {
      setError('Incorrect access password. Please enter the valid key.');
      return;
    }
    setError('');
    setDownloading(true);
    // Trigger direct download with authenticated query
    window.location.href = `/api/download-desktop?password=${encodeURIComponent(clean)}`;
    setTimeout(() => {
      setDownloading(false);
      onClose();
    }, 1500);
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(15, 23, 42, 0.65)',
        backdropFilter: 'blur(4px)',
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#ffffff',
          borderRadius: 16,
          padding: '32px 28px',
          maxWidth: 420,
          width: '100%',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)',
          border: '1px solid var(--c-line, #e2e8f0)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 12,
              backgroundColor: 'var(--c-accent-2, #fef3c7)',
              color: 'var(--c-accent, #d97706)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Ic.download size={22} />
          </div>
          <div>
            <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: 'var(--c-ink, #0f172a)' }}>
              Download Desktop App
            </h3>
            <p style={{ margin: '2px 0 0', fontSize: 13, color: 'var(--c-ink-3, #64748b)' }}>
              Cheatsheet Offline PC Edition (v2.1)
            </p>
          </div>
        </div>

        <p style={{ fontSize: 14, color: 'var(--c-ink-2, #334155)', lineHeight: 1.5, marginBottom: 20 }}>
          Please enter your access key to download the full desktop application package:
        </p>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 16 }}>
            <input
              type="password"
              placeholder="Enter access password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                if (error) setError('');
              }}
              autoFocus
              style={{
                width: '100%',
                padding: '11px 14px',
                borderRadius: 10,
                border: error ? '1.5px solid #ef4444' : '1.5px solid var(--c-line-2, #cbd5e1)',
                fontSize: 15,
                outline: 'none',
                backgroundColor: '#f8fafc',
                color: '#0f172a',
                boxSizing: 'border-box',
              }}
            />
            {error && (
              <p style={{ margin: '6px 0 0', fontSize: 12.5, color: '#ef4444', fontWeight: 500 }}>
                {error}
              </p>
            )}
          </div>

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <Btn variant="ghost" size="md" type="button" onClick={onClose}>
              Cancel
            </Btn>
            <Btn variant="primary" size="md" type="submit" disabled={!password.trim() || downloading}>
              {downloading ? 'Starting...' : 'Unlock & Download'}
            </Btn>
          </div>
        </form>
      </div>
    </div>
  );
}

export function DesktopDownloadBtn({
  variant = 'secondary',
  size = 'xl',
  label = 'Download for PC (v2.1)',
}: {
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'sm' | 'md' | 'lg' | 'xl';
  label?: string;
}) {
  const [open, setOpen] = React.useState(false);

  return (
    <>
      <Btn
        variant={variant}
        size={size}
        icon={<Ic.download size={size === 'xl' ? 15 : 13} />}
        onClick={() => setOpen(true)}
      >
        {label}
      </Btn>
      <DesktopDownloadModal isOpen={open} onClose={() => setOpen(false)} />
    </>
  );
}

export function DesktopDownloadTag() {
  const [open, setOpen] = React.useState(false);

  return (
    <>
      <div onClick={() => setOpen(true)} style={{ cursor: 'pointer' }}>
        <Tag tone="mint" style={{ padding: '5px 12px' }}>
          <Ic.download size={11} /> Plug & Play Desktop App v2.1 Available
        </Tag>
      </div>
      <DesktopDownloadModal isOpen={open} onClose={() => setOpen(false)} />
    </>
  );
}
