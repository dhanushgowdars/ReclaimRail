import { timingSafeEqual } from "node:crypto";

const MAX_REQUEST_BYTES = 4096;

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

export async function POST(request: Request): Promise<Response> {
  const configuredReviewerCode =
    process.env.RECLAIMRAIL_PAYMENT_LAB_REVIEWER_CODE?.trim();
  const backendAccessToken =
    process.env.RECLAIMRAIL_PAYMENT_LAB_ACCESS_TOKEN?.trim();

  if (!configuredReviewerCode || !backendAccessToken) {
    return Response.json(
      { detail: "Payment Lab access is not configured" },
      { status: 503 },
    );
  }

  const reviewerCode = request.headers
    .get("X-ReclaimRail-Reviewer-Code")
    ?.trim();

  if (!reviewerCode || !safeEqual(reviewerCode, configuredReviewerCode)) {
    return Response.json(
      { detail: "Payment Lab access denied" },
      { status: 401 },
    );
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
        "X-ReclaimRail-Lab-Token": backendAccessToken,
      },
      body,
    });

    const responseBody = await upstream.text();
    const contentType = upstream.headers.get("content-type") ?? "application/json";

    return new Response(responseBody, {
      status: upstream.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": contentType,
      },
    });
  } catch {
    return Response.json(
      { detail: "ReclaimRail API is currently unavailable" },
      { status: 503 },
    );
  }
}
