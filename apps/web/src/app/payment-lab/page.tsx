import { Radio, ShieldCheck, Sparkles } from "lucide-react";

import { RecoveryNavigation } from "@/components/recovery-navigation";
import { PaymentLabLauncher } from "@/components/payment-lab-launcher";

export default function PaymentLabPage() {
  return (
    <div className="app-shell">
      <RecoveryNavigation active="lab" />
      <main className="workspace live-demo-workspace">
        <header className="live-demo-header">
          <div>
            <p className="kicker"><Radio size={14} /> Payment recovery control plane</p>
            <h1>A real failure.<br /><em>A bounded response.</em></h1>
            <p>
              Start one controlled Razorpay Test Mode attempt. ReclaimRail only
              advances when signed provider evidence reaches the server.
            </p>
          </div>
          <aside className="live-demo-header__contract" aria-label="Live run contract">
            <span><Sparkles size={15} /> Gemini proposes</span>
            <span><ShieldCheck size={15} /> Policy decides</span>
            <span><Radio size={15} /> Provider proves</span>
            <small>Razorpay Test Mode · no real money moves</small>
          </aside>
        </header>

        <PaymentLabLauncher />
      </main>
    </div>
  );
}
