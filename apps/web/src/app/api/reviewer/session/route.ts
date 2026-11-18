import { NextResponse } from "next/server";

import {
  createReviewerSessionToken,
  reviewerSessionConfigurationReady,
  reviewerSessionCookieName,
  reviewerSessionCookieOptions,
  verifyReviewerAccessCode,
} from "@/lib/reviewer-session";
import { requestHasSameOrigin } from "@/lib/same-origin";

const MAX_REQUEST_BYTES = 1024;
const ATTEMPT_WINDOW_MILLISECONDS = 5 * 60 * 1000;
const MAX_ATTEMPTS_PER_WINDOW = 8;
const MAX_GLOBAL_ATTEMPTS_PER_WINDOW = 128;
const MAX_TRACKED_CLIENTS = 2048;
const attemptsByClient = new Map<string, number[]>();
let globalAttempts: number[] = [];

function noStoreJson(body: object, status: number): NextResponse {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

function clientKey(request: Request): string {
  return (
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    request.headers.get("x-real-ip")?.trim() ||
    "local"
  );
}

function rateLimited(request: Request): boolean {
  const now = Date.now();
  const cutoff = now - ATTEMPT_WINDOW_MILLISECONDS;
  globalAttempts = globalAttempts.filter((attempt) => attempt >= cutoff);
  globalAttempts.push(now);
  if (globalAttempts.length > MAX_GLOBAL_ATTEMPTS_PER_WINDOW) return true;

  const key = clientKey(request);
  if (!attemptsByClient.has(key) && attemptsByClient.size >= MAX_TRACKED_CLIENTS) {
    for (const [trackedKey, attempts] of attemptsByClient) {
      if (attempts.every((attempt) => attempt < cutoff)) {
        attemptsByClient.delete(trackedKey);
      }
    }
    if (attemptsByClient.size >= MAX_TRACKED_CLIENTS) return true;
  }
  const recent = (attemptsByClient.get(key) ?? []).filter(
    (attempt) => attempt >= cutoff,
  );
  recent.push(now);
  attemptsByClient.set(key, recent);
  return recent.length > MAX_ATTEMPTS_PER_WINDOW;
}

export async function POST(request: Request): Promise<NextResponse> {
  if (!requestHasSameOrigin(request)) {
    return noStoreJson({ detail: "Reviewer access denied" }, 403);
  }
  if (!reviewerSessionConfigurationReady()) {
    return noStoreJson({ detail: "Reviewer access is not configured" }, 503);
  }
  if (rateLimited(request)) {
    return noStoreJson({ detail: "Too many access attempts" }, 429);
  }

  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declaredLength) && declaredLength > MAX_REQUEST_BYTES) {
    return noStoreJson({ detail: "Reviewer access request is too large" }, 413);
  }
  const body = await request.text();
  if (new TextEncoder().encode(body).byteLength > MAX_REQUEST_BYTES) {
    return noStoreJson({ detail: "Reviewer access request is too large" }, 413);
  }

  let accessCode = "";
  try {
    const parsed = JSON.parse(body) as { accessCode?: unknown };
    accessCode = typeof parsed.accessCode === "string" ? parsed.accessCode.trim() : "";
  } catch {
    return noStoreJson({ detail: "Reviewer access denied" }, 401);
  }
  if (!(await verifyReviewerAccessCode(accessCode))) {
    return noStoreJson({ detail: "Reviewer access denied" }, 401);
  }

  attemptsByClient.delete(clientKey(request));
  const response = noStoreJson({ authenticated: true }, 200);
  response.cookies.set(
    reviewerSessionCookieName(),
    await createReviewerSessionToken(),
    reviewerSessionCookieOptions(),
  );
  return response;
}

export async function DELETE(request: Request): Promise<NextResponse> {
  if (!requestHasSameOrigin(request)) {
    return noStoreJson({ detail: "Reviewer access denied" }, 403);
  }
  const response = noStoreJson({ authenticated: false }, 200);
  response.cookies.set(reviewerSessionCookieName(), "", {
    ...reviewerSessionCookieOptions(),
    maxAge: 0,
  });
  return response;
}
