import { ReviewerAccessForm } from "@/components/reviewer-access-form";

export default async function ReviewerAccessPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;
  const returnPath = next?.startsWith("/") && !next.startsWith("//") ? next : "/";

  return (
    <main className="reviewer-access-page">
      <section>
        <div className="product-mark" aria-hidden="true"><b>R</b><i /></div>
        <p className="kicker">CONTROLLED REVIEWER DEMO</p>
        <h1>ReclaimRail access</h1>
        <p>
          Operational payment and recovery evidence is restricted to an
          authorized reviewer session. The access code is exchanged once for a
          signed, short-lived HttpOnly cookie and is never stored in browser
          storage.
        </p>
        <ReviewerAccessForm returnPath={returnPath} />
        <small>Razorpay Test Mode · no real money moves</small>
      </section>
    </main>
  );
}
