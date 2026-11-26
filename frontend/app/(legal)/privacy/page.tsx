import type { Metadata } from "next";
import { LegalDocument } from "@/components/legal/LegalDocument";
import { PRODUCT } from "@/lib/legal";

export const metadata: Metadata = { title: "Privacy" };

export default function PrivacyPage() {
  return (
    <LegalDocument title="Privacy">
      <p>
        This page explains what {PRODUCT} keeps about you, why, who else sees it, and your rights under the Nigeria Data
        Protection Act 2023. We keep as little as we need.
      </p>
      <section>
        <h2>What we keep</h2>
        <ul>
          <li><strong>Account:</strong> your name and email (or, for a login from an institution, your name and login ID). Your password is stored only as a one-way scrambled value, never as the password itself. If you turn on two-factor sign-in, an encrypted key for your authenticator app and recovery codes (also scrambled) are stored.</li>
          <li><strong>Sign-in records:</strong> the device type, the address your connection comes from and when you signed in, to keep your account safe and to sign you out of other devices when needed.</li>
          <li><strong>Learning:</strong> your practice results, progress and lessons or progressions you create.</li>
          <li><strong>Payments:</strong> which plan, how many months, the amount, the date and Paystack&apos;s reference. Your card or bank details go to Paystack only.</li>
          <li><strong>Saved card (only if you tick “Renew automatically”):</strong> a token from Paystack that lets us charge that card, plus its brand, last four digits and expiry date. It is stored encrypted, never includes the card number, and is deleted when you forget the card or delete your account.</li>
          <li><strong>Institutions:</strong> the institution&apos;s name, its manager, and the list of logins it has made, with each person&apos;s name and when they last signed in.</li>
          <li><strong>Files you open:</strong> MIDI and audio files are read on your device. Recordings are never uploaded or kept. A MIDI file is kept only if you choose Save to My Library, together with your edits; an audio analysis saved to My Library keeps only your settings and corrections, not the recording. You can delete anything in My Library at any time.</li>
          <li><strong>My Library:</strong> the names you give saved items, your saved chord progressions and the settings of saved work.</li>
        </ul>
      </section>
      <section>
        <h2>Why we use it</h2>
        <ul>
          <li>To run your account and give you access to what you have paid for (contract).</li>
          <li>To email you things you need: sign-up confirmation, password resets, and a reminder before your plan ends. You can switch the plan reminders off in Account Settings.</li>
          <li>To keep the service secure, prevent sharing of logins and fix faults (our legitimate interest).</li>
          <li>To keep payment records as tax and accounting law require (legal duty).</li>
        </ul>
        <p>We do not sell your data, show adverts, or use advertising or tracking cookies.</p>
      </section>
      <section>
        <h2>Cookies</h2>
        <p>
          We use one cookie, to keep you signed in. It is needed for the service to work, so it does not need your consent.
          Your theme and piano settings are saved on your own device.
        </p>
      </section>
      <section>
        <h2>Who else handles it</h2>
        <ul>
          <li><strong>Paystack</strong> takes your payment.</li>
          <li><strong>Resend</strong> delivers our emails, so it sees your email address and the message.</li>
          <li>Our <strong>hosting provider</strong> stores the data on our servers.</li>
          <li>If we turn on error reporting, a technical error report (without your cookies, password or personal details) may go to our error-reporting provider.</li>
        </ul>
        <p>Some of these providers are outside Nigeria. We use them under their data-protection terms. We share data with others only when the law requires it.</p>
      </section>
      <section>
        <h2>Schools, churches and studios</h2>
        <p>
          If an institution gave you a login, the institution is responsible for having the right to enrol you
          (including the permission of a parent or guardian if you are under 18), and can see your name, login ID and
          when you last signed in. It cannot see your password. Ask the institution about what it does with that
          information.
        </p>
      </section>
      <section>
        <h2>How long we keep it</h2>
        <p>
          We keep account data while your account is open. You can delete your account yourself in Account Settings: your name,
          email, saved library, practice results and sign-in records are erased at once and cannot be recovered. We keep only
          the payment records the law requires (plan, amount, date and reference, for several years), without your name or
          email. Closing an account is different: it stops you signing in but keeps your data.
        </p>
      </section>
      <section>
        <h2>Your rights</h2>
        <p>
          You can see and download the data we hold about you (Account Settings, Download my data), correct your name and
          change your email there, delete your account there, or switch off our reminder emails. For anything else, such as
          objecting to how we use your data, write to us using the contact below; we will answer within a reasonable time.
          You can also complain to the Nigeria Data Protection Commission.
        </p>
      </section>
    </LegalDocument>
  );
}
