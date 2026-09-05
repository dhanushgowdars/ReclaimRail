import {
  BookCheck,
  Boxes,
  BrainCircuit,
  FlaskConical,
  LayoutDashboard,
  ListChecks,
  Play,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

const navigation = [
  { id: "lab", href: "/payment-lab", label: "Live demo", icon: Play, live: true },
  { id: "overview", href: "/", label: "Command center", icon: LayoutDashboard },
  { id: "queue", href: "/cases", label: "Recovery cases", icon: Boxes },
  { id: "reviews", href: "/reviews", label: "Human reviews", icon: ListChecks },
  { id: "outcomes", href: "/outcomes", label: "Outcome ledger", icon: BookCheck },
  { id: "controls", href: "/safety-controls", label: "Safety controls", icon: ShieldCheck },
  { id: "intelligence", href: "/intelligence", label: "Recovery Brain", icon: BrainCircuit },
  { id: "evaluations", href: "/evaluations", label: "Evidence Lab", icon: FlaskConical },
] as const;

export function RecoveryNavigation({ active = "overview" }: { active?: (typeof navigation)[number]["id"] | "case" }) {
  return (
    <header className="sidebar">
      <Link className="product-lockup" href="/" aria-label="ReclaimRail overview">
        <span className="product-mark" aria-hidden="true"><b>R</b><i /></span>
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
