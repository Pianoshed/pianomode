/** "JBSWY3DPEHPK3PXP" -> "JBSW Y3DP EHPK 3PXP": easier to read aloud and type into an app. */
export function groupSecret(secret: string): string {
  return secret.replace(/\s+/g, "").replace(/(.{4})/g, "$1 ").trim();
}

/** The recovery codes as a text file the person can keep. */
export function recoveryCodesText(codes: readonly string[], account: string): string {
  return [
    "Keystudy recovery codes",
    `Account: ${account}`,
    "",
    "Each code works once, if you lose your authenticator app.",
    "Keep this file somewhere safe and private.",
    "",
    ...codes,
    "",
  ].join("\n");
}
