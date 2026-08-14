export function Spinner({ label }: { label: string }) {
  return (
    <span role="status" aria-label={label} className="spinner">
      <span className="spinner-ring" aria-hidden="true" />
    </span>
  )
}
