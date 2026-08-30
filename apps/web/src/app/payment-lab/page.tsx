import { Radio } from "lucide-react";

import { RecoveryNavigation } from "@/components/recovery-navigation";
import { PaymentLabLauncher } from "@/components/payment-lab-launcher";

export default function PaymentLabPage() {
  return (
    <div className="app-shell">
      <RecoveryNavigation active="lab" />
      <main className="workspace live-demo-workspace">
        <header className="live-demo-header">
          <div>
            <p className="kicker"><Radio size={14} /> Provider-backed demonstration</p>
            <h1>Live recovery demo</h1>
            <p>
              Start one protected Razorpay Test Mode attempt, then follow only
              evidence the recovery system has actually received.
            </p>
          </div>
          <span className="test-mode test-mode--large">
            <i /> Razorpay Test Mode
          </span>
        </header>

        <PaymentLabLauncher />
      </main>
    </div>
  );
}
