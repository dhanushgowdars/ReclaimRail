import { cookies } from "next/headers";

import {
  reviewerSessionCookieName,
  verifyReviewerSessionToken,
} from "@/lib/reviewer-session";
import { requestHasSameOrigin } from "@/lib/same-origin";

const MAX_REQUEST_BYTES = 4096;
const PAYMENT_LAB_RUN_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function apiBaseUrl(): string {
  return (
    process.env.RECLAIMRAIL_API_BASE_URL?.replace(/\/$/, "") ??
    "http://127.0.0.1:8000"
  );
}

async function getPaymentLabAccess(): Promise<
  | { backendAccessToken: string }
  | { response: Response }
> {
  const backendAccessToken =
    process.env.RECLAIMRAIL_PAYMENT_LAB_ACCESS_TOKEN?.trim();

  if (!backendAccessToken) {
    return {
      response: Response.json(
        { detail: "Payment Lab access is not configured" },
        { status: 503 },
      ),
    };
  }

  const cookieStore = await cookies();
  const authenticated = await verifyReviewerSessionToken(
    cookieStore.get(reviewerSessionCookieName())?.value,
  );
  if (!authenticated) {
    return {
      response: Response.json(
        { detail: "Payment Lab access denied" },
        { status: 401 },
      ),
    };
  }

  return { backendAccessToken };
}

function upstreamResponse(upstream: Response, body: string): Response {
  return new Response(body, {
    status: upstream.status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type":
        upstream.headers.get("content-type") ?? "application/json",
    },
  });
}

export async function GET(request: Request): Promise<Response> {
  const access = await getPaymentLabAccess();

  if ("response" in access) {
    return access.response;
  }

  const searchParams = new URL(request.url).searchParams;
  const verifiedReplay = searchParams.get("verified_replay");
  const paymentLabRunId = searchParams.get("payment_lab_run_id")?.trim();

  if (verifiedReplay && verifiedReplay !== "latest") {
    return Response.json(
      { detail: "Unknown Payment Lab replay request" },
      { status: 400 },
    );
  }

  if (!verifiedReplay && (!paymentLabRunId || !PAYMENT_LAB_RUN_ID_PATTERN.test(paymentLabRunId))) {
    return Response.json(
      { detail: "A valid Payment Lab run ID is required" },
      { status: 400 },
    );
  }

  try {
    const upstreamPath = verifiedReplay
      ? "/payment-lab/replays/latest"
      : `/payment-lab/runs/${encodeURIComponent(paymentLabRunId ?? "")}`;
    const upstream = await fetch(
      `${apiBaseUrl()}${upstreamPath}`,
      {
        cache: "no-store",
        signal: AbortSignal.timeout(10_000),
        headers: {
          Accept: "application/json",
          "X-ReclaimRail-Lab-Token": access.backendAccessToken,
        },
      },
    );

    return upstreamResponse(upstream, await upstream.text());
  } catch {
    return Response.json(
      { detail: "ReclaimRail API is currently unavailable" },
      { status: 503 },
    );
  }
}

export async function POST(request: Request): Promise<Response> {
  if (!requestHasSameOrigin(request)) {
    return Response.json({ detail: "Payment Lab access denied" }, { status: 403 });
  }
  const access = await getPaymentLabAccess();

  if ("response" in access) {
    return access.response;
  }

  const declaredLength = Number(request.headers.get("content-length") ?? "0");

  if (Number.isFinite(declaredLength) && declaredLength > MAX_REQUEST_BYTES) {
    return Response.json(
      { detail: "Payment Lab request is too large" },
      { status: 413 },
    );
  }

  const body = await request.text();

  if (Buffer.byteLength(body, "utf8") > MAX_REQUEST_BYTES) {
    return Response.json(
      { detail: "Payment Lab request is too large" },
      { status: 413 },
    );
  }

  try {
    JSON.parse(body);
  } catch {
    return Response.json(
      { detail: "Payment Lab request must be valid JSON" },
      { status: 400 },
    );
  }

  try {
    const upstream = await fetch(`${apiBaseUrl()}/payment-lab/runs`, {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-ReclaimRail-Lab-Token": access.backendAccessToken,
      },
      body,
    });

    return upstreamResponse(upstream, await upstream.text());
  } catch {
    return Response.json(
      { detail: "ReclaimRail API is currently unavailable" },
      { status: 503 },
    );
  }
}
