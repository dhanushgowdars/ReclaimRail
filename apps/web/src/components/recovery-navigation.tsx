import {
  BookCheck,
  Boxes,
  LayoutDashboard,
  Play,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

const navigation = [
  { id: "lab", href: "/payment-lab", label: "Live demo", icon: Play, live: true },
  { id: "overview", href: "/", label: "Command center", icon: LayoutDashboard },
  { id: "queue", href: "/#recovery-queue", label: "Recovery cases", icon: Boxes },
  { id: "outcomes", href: "/#outcomes", label: "Outcome ledger", icon: BookCheck },
  { id: "controls", href: "/#safety-controls", label: "Safety controls", icon: ShieldCheck },
] as const;

export function RecoveryNavigation({ active = "overview" }: { active?: "overview" | "case" | "lab" }) {
  return (
    <header className="sidebar">
      <Link className="product-lockup" href="/" aria-label="ReclaimRail overview">
        <span className="product-mark">R</span>
        <span className="product-lockup__copy">
          <strong>ReclaimRail</strong>
          <small>Recovery control plane</small>
        </span>
      </Link>
      <nav aria-label="Command center navigation" className="navigation">
        {navigation.map((item) => {
          const Icon = item.icon;
          const isActive = active === item.id || (active === "case" && item.id === "queue");
          return (
            <div key={item.id}>
              <Link
                className={`navigation__item${isActive ? " navigation__item--active" : ""}`}
                href={item.href}
              >
                <Icon aria-hidden="true" size={19} strokeWidth={2} />
                <span>{item.label}</span>
                {"live" in item ? <em>LIVE</em> : null}
              </Link>
            </div>
          );
        })}
      </nav>
      <div className="sidebar__footer">
        <strong><i aria-hidden="true" /> Razorpay Test Mode</strong>
        <span>Provider evidence only</span>
      </div>
    </header>
  );
}
