import Image from "next/image";

/**
 * Author portrait with an initials fallback while the static portrait is absent.
 */
export default function AuthorAvatar({
  name,
  src,
  size = 44,
  className = "",
}: {
  name: string;
  src?: string;
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
      className={`relative flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-brand-600 font-display font-bold text-white ${className}`}
    >
      {src ? (
        <Image
          src={src}
          alt=""
          fill
          sizes={`${size}px`}
          className="object-cover"
        />
      ) : (
        initials
      )}
    </span>
  );
}
