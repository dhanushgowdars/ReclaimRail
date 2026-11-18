const SESSION_COOKIE_NAME = "reclaimrail_reviewer_session";
const DEFAULT_SESSION_TTL_SECONDS = 4 * 60 * 60;
const MINIMUM_SECRET_LENGTH = 32;

function configuredSessionSecret(): string | null {
  const secret = process.env.RECLAIMRAIL_REVIEWER_SESSION_SECRET?.trim();
  return secret && secret.length >= MINIMUM_SECRET_LENGTH ? secret : null;
}

function sessionTtlSeconds(): number {
  const configured = Number(
    process.env.RECLAIMRAIL_REVIEWER_SESSION_TTL_SECONDS ??
      DEFAULT_SESSION_TTL_SECONDS,
  );
  if (!Number.isSafeInteger(configured)) return DEFAULT_SESSION_TTL_SECONDS;
  return Math.min(Math.max(configured, 300), 24 * 60 * 60);
}

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/u, "");
}

async function hmac(message: string, secret: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return base64Url(
    new Uint8Array(
      await crypto.subtle.sign("HMAC", key, encoder.encode(message)),
    ),
  );
}

export function reviewerSessionConfigurationReady(): boolean {
  return Boolean(
    configuredSessionSecret() &&
      process.env.RECLAIMRAIL_REVIEWER_ACCESS_CODE?.trim(),
  );
}

export function reviewerSessionCookieName(): string {
  return SESSION_COOKIE_NAME;
}

export function reviewerSessionCookieOptions(): {
  httpOnly: true;
  sameSite: "strict";
  secure: boolean;
  path: "/";
  maxAge: number;
} {
  return {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: sessionTtlSeconds(),
  };
}

export async function createReviewerSessionToken(): Promise<string> {
  const secret = configuredSessionSecret();
  if (!secret) throw new Error("Reviewer session signing is not configured");

  const expiresAt = Math.floor(Date.now() / 1000) + sessionTtlSeconds();
  const nonce = base64Url(crypto.getRandomValues(new Uint8Array(18)));
  const payload = `${expiresAt}.${nonce}`;
  return `${payload}.${await hmac(payload, secret)}`;
}

export async function verifyReviewerSessionToken(
  token: string | undefined,
): Promise<boolean> {
  const secret = configuredSessionSecret();
  if (!secret || !token) return false;

  const parts = token.split(".");
  if (parts.length !== 3) return false;
  const [expiresAtText, nonce, suppliedSignature] = parts;
  if (!/^\d{10}$/u.test(expiresAtText) || !/^[A-Za-z0-9_-]{20,32}$/u.test(nonce)) {
    return false;
  }
  const expiresAt = Number(expiresAtText);
  if (!Number.isSafeInteger(expiresAt) || expiresAt <= Math.floor(Date.now() / 1000)) {
    return false;
  }

  const expectedSignature = await hmac(`${expiresAtText}.${nonce}`, secret);
  if (expectedSignature.length !== suppliedSignature.length) return false;

  let mismatch = 0;
  for (let index = 0; index < expectedSignature.length; index += 1) {
    mismatch |=
      expectedSignature.charCodeAt(index) ^ suppliedSignature.charCodeAt(index);
  }
  return mismatch === 0;
}

export async function verifyReviewerAccessCode(code: string): Promise<boolean> {
  const configured = process.env.RECLAIMRAIL_REVIEWER_ACCESS_CODE?.trim();
  if (!configured || !code) return false;

  const encoder = new TextEncoder();
  const [expected, supplied] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(configured)),
    crypto.subtle.digest("SHA-256", encoder.encode(code)),
  ]);
  const expectedBytes = new Uint8Array(expected);
  const suppliedBytes = new Uint8Array(supplied);
  let mismatch = 0;
  for (let index = 0; index < expectedBytes.length; index += 1) {
    mismatch |= expectedBytes[index] ^ suppliedBytes[index];
  }
  return mismatch === 0;
}
