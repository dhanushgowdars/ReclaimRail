import { timingSafeEqual } from "node:crypto";

const MAX_REQUEST_BYTES = 4096;
const PAYMENT_LAB_RUN_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function apiBaseUrl(): string {
  return (
    process.env.RECLAIMRAIL_API_BASE_URL?.replace(/\/$/, "") ??
    "http://127.0.0.1:8000"
  );
}

function safeEqual(left: string, right: string): boolean {
  const leftBytes = Buffer.from(left);
  const rightBytes = Buffer.from(right);

  return (
    leftBytes.length === rightBytes.length &&
    timingSafeEqual(leftBytes, rightBytes)
  );
}

function getPaymentLabAccess(request: Request):
  | { backendAccessToken: string }
  | { response: Response } {
  const configuredReviewerCode =
    process.env.RECLAIMRAIL_PAYMENT_LAB_REVIEWER_CODE?.trim();
  const backendAccessToken =
    process.env.RECLAIMRAIL_PAYMENT_LAB_ACCESS_TOKEN?.trim();

  if (!configuredReviewerCode || !backendAccessToken) {
    return {
      response: Response.json(
        { detail: "Payment Lab access is not configured" },
        { status: 503 },
      ),
    };
  }

  const reviewerCode = request.headers
    .get("X-ReclaimRail-Reviewer-Code")
    ?.trim();

  if (!reviewerCode || !safeEqual(reviewerCode, configuredReviewerCode)) {
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
  const access = getPaymentLabAccess(request);

  if ("response" in access) {
    return access.response;
  }

  const paymentLabRunId = new URL(request.url).searchParams
    .get("payment_lab_run_id")
    ?.trim();

  if (!paymentLabRunId || !PAYMENT_LAB_RUN_ID_PATTERN.test(paymentLabRunId)) {
    return Response.json(
      { detail: "A valid Payment Lab run ID is required" },
      { status: 400 },
    );
  }

  try {
    const upstream = await fetch(
      `${apiBaseUrl()}/payment-lab/runs/${encodeURIComponent(paymentLabRunId)}`,
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
  const access = getPaymentLabAccess(request);

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
