/**
 * Initials avatar for an author byline.
 *
 * The roster carries no portrait photography, and inventing faces for these bylines
 * would be worse than having none — so identity is carried by initials in brand
 * colours. Swap in next/image here when real portraits exist.
 */
export default function AuthorAvatar({
  name,
  size = 44,
  className = "",
}: {
  name: string;
  size?: number;
  className?: string;
}) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");

  return (
    <span
      aria-hidden="true"
      style={{ width: size, height: size }}
      className={`flex shrink-0 items-center justify-center rounded-full bg-brand-600 font-display font-bold text-white ${className}`}
    >
      {initials}
    </span>
  );
}
