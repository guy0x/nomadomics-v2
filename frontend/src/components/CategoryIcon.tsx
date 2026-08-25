import { Landmark, Plane, Wallet, MapPin, ShieldCheck, Globe } from "./Icons";

const MAP = {
  banking: Wallet,
  taxes: Landmark,
  travel: Plane,
  gear: ShieldCheck,
  cities: MapPin,
} as const;

export default function CategoryIcon({ slug, className }: { slug: string; className?: string }) {
  const Icon = (MAP as Record<string, typeof Globe>)[slug] ?? Globe;
  return <Icon className={className} />;
}
