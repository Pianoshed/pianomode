import { api } from "@/lib/api";

export const setupTwoFactor = () => api<{ secret: string; uri: string }>("/api/v1/auth/2fa/setup", { method: "POST" });
export const enableTwoFactor = (code: string) =>
  api<{ recovery_codes: string[] }>("/api/v1/auth/2fa/enable", { method: "POST", body: { code } });
export const disableTwoFactor = (password: string, code: string) =>
  api<void>("/api/v1/auth/2fa/disable", { method: "POST", body: { password, code } });
export const newRecoveryCodes = (code: string) =>
  api<{ recovery_codes: string[] }>("/api/v1/auth/2fa/recovery-codes", { method: "POST", body: { code } });

export const changeEmail = (new_email: string, password: string) =>
  api<{ message: string }>("/api/v1/account/change-email", { method: "POST", body: { new_email, password } });
export const confirmEmailChange = (token: string) =>
  api<{ message: string }>("/api/v1/account/confirm-email-change", { method: "POST", body: { token } });
export const deleteAccount = (password: string, confirm: string, otp?: string) =>
  api<void>("/api/v1/account/delete", { method: "POST", body: { password, confirm, ...(otp ? { otp } : {}) } });

export const EXPORT_URL = "/api/v1/account/export";
