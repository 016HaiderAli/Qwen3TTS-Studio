const LABELS: Record<string, string> = {
  draft: 'Draft',
  designing: 'Designing…',
  preview_ready: 'Preview ready',
  approving: 'Approving…',
  approved: 'Approved',
  queued: 'Queued',
  running: 'Processing…',
  ready: 'Ready',
  failed: 'Failed',
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${status}`}>{LABELS[status] ?? status}</span>
}
