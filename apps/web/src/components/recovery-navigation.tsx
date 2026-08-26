import Link from "next/link";

type GlyphName = "grid" | "play" | "queue" | "shield" | "pulse" | "receipt";

function Glyph({ name }: { name: GlyphName }) {
  const paths = {
    grid: <path d="M4 4h6v6H4V4Zm10 0h6v6h-6V4ZM4 14h6v6H4v-6Zm10 0h6v6h-6v-6Z" />,
    play: <path d="M8 5v14l11-7L8 5Z" />,
    queue: <path d="M4 6h16M4 12h16M4 18h11" />,
    shield: <path d="M12 3 19 6v5c0 4.4-2.9 8.2-7 10-4.1-1.8-7-5.6-7-10V6l7-3Zm-3 9 2 2 4-4" />,
    pulse: <path d="M3 12h4l2.2-5 3.6 10 2.1-5H21" />,
    receipt: <path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3Zm3 5h6M9 12h6" />,
  };

  return <svg aria-hidden="true" className="glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

export function RecoveryNavigation({ active = "overview" }: { active?: "overview" | "case" | "lab" }) {
  return <aside className="sidebar">
    <div className="product-lockup"><span className="product-mark">R</span><div><strong>ReclaimRail</strong><span>Recovery control plane</span></div></div>
    <nav aria-label="Command center navigation" className="navigation">
      <Link className={`navigation__item ${active === "overview" ? "navigation__item--active" : ""}`} href="/"><Glyph name="grid" />Overview</Link>
      <Link className={`navigation__item ${active === "lab" ? "navigation__item--active" : ""}`} href="/payment-lab"><Glyph name="play" />Payment Lab</Link>
      <Link className="navigation__item" href="/#recovery-queue"><Glyph name="queue" />Recovery queue</Link>
      <Link className="navigation__item" href="/#outcomes"><Glyph name="receipt" />Outcome ledger</Link>
      <Link className="navigation__item" href="/#incidents"><Glyph name="pulse" />Rail incidents</Link>
      <Link className="navigation__item" href="/#safety-controls"><Glyph name="shield" />Safety controls</Link>
    </nav>
    <div className="sidebar__footer"><span className="sidebar__footer-label">Control model</span><strong>AI proposes. Policy decides.</strong><p>Every provider action is bounded, idempotent, and auditable.</p></div>
  </aside>;
}
