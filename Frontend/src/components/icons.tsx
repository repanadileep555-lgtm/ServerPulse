import type { NavIconName } from './navigation'

const PATHS: Record<NavIconName, string> = {
  overview: 'M3 11l9-7 9 7M5 10v10h14V10',
  system: 'M3 12h4l3-7 4 14 3-7h4',
  account: 'M12 4a4 4 0 1 1 0 8 4 4 0 1 1 0-8z M4 21c0-4 3.6-7 8-7s8 3 8 7',
  accounts: 'M9 4a4 4 0 1 1 0 8 4 4 0 1 1 0-8z M1 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1 M19 8v6 M16 11h6',
  session: 'M12 3l7 3v5c0 4.5-3 8.2-7 9.5-4-1.3-7-5-7-9.5V6l7-3z',
  collapse: 'M15 6l-6 6 6 6',
  signout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4 M16 17l5-5-5-5 M21 12H9',
  refresh: 'M21 12a9 9 0 1 1-2.6-6.3 M21 4v5h-5',
}

export function NavIcon({ name }: { name: NavIconName }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="nav-icon"
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
