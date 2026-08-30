import {
  Activity,
  ArrowUpRight,
  BookCheck,
  Boxes,
  LayoutDashboard,
  Play,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

const navigation = [
  { id: "overview", href: "/", label: "Overview", icon: LayoutDashboard },
  { id: "lab", href: "/payment-lab", label: "Payment Lab", icon: Play, live: true },
  { id: "queue", href: "/#recovery-queue", label: "Recovery queue", icon: Boxes },
  { id: "outcomes", href: "/#outcomes", label: "Outcome ledger", icon: BookCheck },
  { id: "incidents", href: "/#incidents", label: "Rail incidents", icon: Activity },
  { id: "controls", href: "/#safety-controls", label: "Safety controls", icon: ShieldCheck },
] as const;

export function RecoveryNavigation({ active = "overview" }: { active?: "overview" | "case" | "lab" }) {
  return (
    <aside className="sidebar">
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
          const isActive = active === item.id;
          return (
            <Link
              className={`navigation__item${isActive ? " navigation__item--active" : ""}`}
              href={item.href}
              key={item.id}
            >
              <Icon aria-hidden="true" size={19} strokeWidth={2} />
              <span>{item.label}</span>
              {"live" in item ? <em>LIVE</em> : <ArrowUpRight className="navigation__arrow" size={15} />}
            </Link>
          );
        })}
      </nav>
      <div className="sidebar__footer">
        <span className="sidebar__footer-label">Control model</span>
        <strong><ShieldCheck size={17} /> AI proposes. Policy decides.</strong>
        <p>Every provider action is bounded, idempotent, and auditable.</p>
      </div>
    </aside>
  );
}
