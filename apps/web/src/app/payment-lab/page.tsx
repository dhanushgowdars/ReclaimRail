import { RecoveryNavigation } from "@/components/recovery-navigation";
import { PaymentLabLauncher } from "@/components/payment-lab-launcher";

export default function PaymentLabPage() {
  return (
    <div className="app-shell">
      <RecoveryNavigation active="lab" />
      <main className="workspace payment-lab-workspace">
        <header className="payment-lab-header">
          <div>
            <p className="kicker">Provider-live recovery lab</p>
            <h1>Fail a real test payment. Watch recovery begin.</h1>
            <p>
              Create a genuine Razorpay Test Mode Order, complete the hosted
              payment journey, and let signed provider evidence trigger the bounded
              recovery system.
            </p>
          </div>
          <span className="test-mode test-mode--large">
            <i /> Razorpay Test Mode
          </span>
        </header>

        <div className="lab-value-strip" aria-label="Live workflow summary">
          <div>
            <span>01</span>
            <strong>Payment attempt</strong>
            <p>Razorpay-hosted Checkout</p>
          </div>
          <div>
            <span>02</span>
            <strong>Verified failure</strong>
            <p>Signed webhook ingestion</p>
          </div>
          <div>
            <span>03</span>
            <strong>Bounded agent</strong>
            <p>Gemini proposal + policy</p>
          </div>
          <div>
            <span>04</span>
            <strong>Measured outcome</strong>
            <p>Evidence-backed ledger</p>
          </div>
        </div>

        <PaymentLabLauncher />

        <section className="lab-assurance-grid">
          <article>
            <p className="kicker">Provider truth</p>
            <h2>Not a simulated dashboard trigger</h2>
            <p>
              Every guided or custom run starts with a real server-created Razorpay
              Test Mode Order. The browser cannot declare financial success.
            </p>
          </article>
          <article>
            <p className="kicker">Bounded autonomy</p>
            <h2>AI cannot move money by itself</h2>
            <p>
              Gemini can propose an intervention. Deterministic policy, incidents,
              consent, idempotency, and stopping rules retain authority.
            </p>
          </article>
          <article>
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
