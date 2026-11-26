const paths: Record<string, string> = {
  dashboard: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  cameras: "M3 6h12v12H3z M15 10l6-4v12l-6-4",
  recordings: "M4 3h16v18H4z M9 8l7 4-7 4z",
  system: "M7 7h10v10H7z M9 1v6 M15 1v6 M9 17v6 M15 17v6 M1 9h6 M1 15h6 M17 9h6 M17 15h6",
  users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M22 21v-2a4 4 0 0 0-3-4 M16 3a4 4 0 0 1 0 8",
  roles: "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M8 12l3 3 5-6",
  audit: "M8 3h12v18H4V7 M8 3v4H4 M8 11h8 M8 15h8 M8 18h5",
};
export default function Icon({ name }: { name: string }) {
  return <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] ?? paths.dashboard} /></svg>;
}
