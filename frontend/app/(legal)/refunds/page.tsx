import type { Metadata } from "next";
import { LegalDocument } from "@/components/legal/LegalDocument";
import { PRODUCT } from "@/lib/legal";

export const metadata: Metadata = { title: "Refunds" };

export default function RefundsPage() {
  return (
    <LegalDocument title="Refunds">
      <p>
        Each payment to {PRODUCT} buys a fixed period of access, and nothing renews by itself unless you ticked “Renew automatically” when paying by card (where that option is offered), so you are never charged
        again without choosing to. An automatic renewal is refunded on the same terms as any other payment. Because access starts straight away, this is how refunds work.
      </p>
      <section>
        <h2>We will refund or fix</h2>
        <ul>
          <li>A payment that was taken twice, or for the wrong amount.</li>
          <li>A payment that went through but did not give you the access you paid for, and that we cannot put right quickly.</li>
          <li>A period in which {PRODUCT} was unavailable for a long time because of a fault on our side. We may add time to your plan instead of refunding.</li>
        </ul>
      </section>
      <section>
        <h2>We do not refund</h2>
        <ul>
          <li>Time that has already started, if you change your mind or no longer need it.</li>
          <li>Access lost because a login was shared or the terms were broken.</li>
          <li>For institution plans, logins you created but did not use, or people you no longer need to give a login.</li>
        </ul>
        <p>The free trial is there so you can try before you pay.</p>
      </section>
      <section>
        <h2>How to ask</h2>
        <p>
          Write to us within 14 days of the payment with the email on your account and the date and amount. Refunds go
          back to the way you paid, through Paystack, and can take several working days to show.
        </p>
      </section>
    </LegalDocument>
  );
}
