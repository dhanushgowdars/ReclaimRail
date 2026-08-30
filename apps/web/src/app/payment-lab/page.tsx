import { ArrowDown, BadgeIndianRupee, Radio, ShieldCheck } from "lucide-react";

import { RecoveryNavigation } from "@/components/recovery-navigation";
import { PaymentLabLauncher } from "@/components/payment-lab-launcher";

export default function PaymentLabPage() {
  return (
    <div className="app-shell">
      <RecoveryNavigation active="lab" />
      <main className="workspace payment-lab-workspace">
        <header className="payment-lab-header">
          <div>
            <p className="kicker"><Radio size={14} /> Provider-live recovery lab</p>
            <h1>Watch a failed payment become a <span>controlled recovery.</span></h1>
            <p>
              One real Razorpay Test Mode failure. Seven durable backend events.
              One auditable recovery decision—revealed as it happens.
            </p>
          </div>
          <span className="test-mode test-mode--large">
            <i /> Razorpay Test Mode
          </span>
        </header>

        <section className="lab-demo-guide" aria-labelledby="demo-guide-title">
          <div className="lab-demo-guide__intro">
            <span>Judge demo</span>
            <h2 id="demo-guide-title">Three moves. The system does the rest.</h2>
          </div>
          <div>
            <span className="lab-demo-guide__number">1</span>
            <strong>Start the live run</strong>
            <p>Use the supplied reviewer code.</p>
          </div>
          <div>
            <span className="lab-demo-guide__number">2</span>
            <strong>Fail Razorpay Checkout</strong>
            <p>Choose Netbanking and trigger Test Mode failure.</p>
          </div>
          <div>
            <span className="lab-demo-guide__number">3</span>
            <strong>Watch verified events</strong>
            <p>Each stage appears only after backend evidence exists.</p>
          </div>
        </section>

        <div className="lab-start-pointer"><ArrowDown size={17} /><span>Configure the provider attempt</span></div>

        <PaymentLabLauncher />

        <section className="lab-assurance-grid" aria-label="Recovery guarantees">
          <article>
            <BadgeIndianRupee size={22} />
            <p className="kicker">Provider truth</p>
            <h2>Not a simulated dashboard trigger</h2>
            <p>
              Every guided or custom run starts with a real server-created Razorpay
              Test Mode Order. The browser cannot declare financial success.
            </p>
          </article>
          <article>
            <ShieldCheck size={22} />
            <p className="kicker">Bounded autonomy</p>
            <h2>AI cannot move money by itself</h2>
            <p>
              Gemini can propose an intervention. Deterministic policy, incidents,
              consent, idempotency, and stopping rules retain authority.
            </p>
          </article>
          <article>
            <Radio size={22} />
            <p className="kicker">Privacy by construction</p>
            <h2>Payment credentials stay with Razorpay</h2>
            <p>
              Checkout is provider-hosted. ReclaimRail persists bounded run and
              evidence identifiers, not card, UPI, email, or contact details.
            </p>
          </article>
        </section>
      </main>
    </div>
  );
}
