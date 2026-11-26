import type { Metadata } from "next";
import { LegalDocument } from "@/components/legal/LegalDocument";
import { PRODUCT } from "@/lib/legal";

export const metadata: Metadata = { title: "Terms of use" };

export default function TermsPage() {
  return (
    <LegalDocument title="Terms of use">
      <p>
        These terms are the agreement between you and the company that runs {PRODUCT} (&quot;we&quot;). By creating an
        account or using {PRODUCT} you agree to them. If you use a login given to you by a school, church or studio,
        you also agree to them for that login.
      </p>
      <section>
        <h2>Your account</h2>
        <ul>
          <li>Give true details and keep your password private. You are responsible for what happens on your account.</li>
          <li>One login is for one person. Do not share your login or password with anyone else.</li>
          <li>Logins given out by an institution can be used on one device at a time. Signing in on a second device signs the first one out.</li>
          <li>You must be old enough to agree to these terms where you live. If you are under 18, a parent, guardian or your institution must agree on your behalf.</li>
        </ul>
      </section>
      <section>
        <h2>Plans and payment</h2>
        <ul>
          <li>Prices are shown in naira at checkout, before you pay. Payments are taken by Paystack; we never see or store your card details.</li>
          <li>Each payment buys a fixed period of access (30 days for each month paid). <strong>Plans do not renew by themselves</strong> and we never charge you again unless you choose to pay, with one exception: where the option is offered, you may tick “Renew automatically” when paying by card. Then, about a day before your plan ends, we charge one more month at the price then shown, and email you before and after. You can turn this off, or forget the saved card, on the Subscription page at any time, and it applies to future charges only.</li>
          <li>When your period ends, lessons, practice and the studio tools lock until you pay again. Your account and saved progress stay.</li>
          <li>We may offer a free trial. A trial can be used once per account.</li>
          <li>An institution plan gives the institution a set number of separate logins for its people. The institution decides who gets one, and is responsible for them.</li>
          <li>We may change prices. A change does not affect time you have already paid for.</li>
        </ul>
        <p>Refunds are covered in our <a className="underline underline-offset-4" href="/refunds">refund policy</a>.</p>
      </section>
      <section>
        <h2>Using {PRODUCT}</h2>
        <ul>
          <li>Use it for your own learning and teaching. Do not copy, resell or scrape the lessons, or try to break or overload the service.</li>
          <li>Do not upload files you have no right to use. Audio and MIDI files you open are processed to give you results; keep the rights of others in mind.</li>
          <li>Chord and key results from the Audio Analyzer are estimates. They can be wrong, especially on busy or noisy recordings.</li>
        </ul>
      </section>
      <section>
        <h2>Our content</h2>
        <p>
          The lessons, exercises, software and design belong to us or our licensors. You get a personal, non-transferable
          right to use them while your access is active. Content you create (such as lessons an educator writes) stays
          yours; you allow us to store and show it as the service needs.
        </p>
      </section>
      <section>
        <h2>When things go wrong</h2>
        <ul>
          <li>We work to keep {PRODUCT} available but cannot promise it will never be interrupted or error-free.</li>
          <li>To the extent the law allows, we are not liable for indirect or lost-profit losses, and our total liability for any claim is limited to what you paid us in the 3 months before it. Nothing here limits rights you have under Nigerian consumer law that cannot be limited.</li>
          <li>We may suspend or close an account that breaks these terms. You can close your account at any time in Account Settings (or ask your institution to close a login).</li>
        </ul>
      </section>
      <section>
        <h2>Changes and law</h2>
        <p>
          We may update these terms. We will change the date above, and for important changes tell you by email or in the
          app. Using {PRODUCT} after a change means you accept it. These terms are governed by the laws of the Federal
          Republic of Nigeria.
        </p>
      </section>
    </LegalDocument>
  );
}
