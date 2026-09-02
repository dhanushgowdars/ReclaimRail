import { timingSafeEqual } from "node:crypto";

const MAX_REQUEST_BYTES = 4096;
const UUID_PATTERN =
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
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}

function requireDemoReviewer(request: Request): Response | null {
  const configuredReviewerCode =
    process.env.RECLAIMRAIL_PAYMENT_LAB_REVIEWER_CODE?.trim();
  const reviewerCode = request.headers.get("X-ReclaimRail-Reviewer-Code")?.trim();

  if (!configuredReviewerCode) {
    return Response.json({ detail: "Payment Lab reviewer access is not configured" }, { status: 503 });
  }
  if (!reviewerCode || !safeEqual(reviewerCode, configuredReviewerCode)) {
    return Response.json({ detail: "Reviewer access denied" }, { status: 401 });
  }
  return null;
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ approvalId: string }> },
): Promise<Response> {
  const denied = requireDemoReviewer(request);
  if (denied) return denied;

  const operatorToken = process.env.RECLAIMRAIL_RECOVERY_OPERATOR_ACCESS_TOKEN?.trim();
  if (!operatorToken) {
    return Response.json(
      { detail: "Protected-review access is not configured on the server" },
      { status: 503 },
    );
  }

  const { approvalId } = await params;
  if (!UUID_PATTERN.test(approvalId)) {
    return Response.json({ detail: "A valid approval ID is required" }, { status: 400 });
  }

  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(contentLength) && contentLength > MAX_REQUEST_BYTES) {
    return Response.json({ detail: "Approval decision is too large" }, { status: 413 });
  }
  const body = await request.text();
  if (Buffer.byteLength(body, "utf8") > MAX_REQUEST_BYTES) {
    return Response.json({ detail: "Approval decision is too large" }, { status: 413 });
  }

  try {
    JSON.parse(body);
  } catch {
    return Response.json({ detail: "Approval decision must be valid JSON" }, { status: 400 });
  }

  try {
    const upstream = await fetch(
      `${apiBaseUrl()}/recovery/approvals/${encodeURIComponent(approvalId)}/decision`,
      {
        method: "POST",
        cache: "no-store",
        signal: AbortSignal.timeout(10_000),
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-ReclaimRail-Operator-Token": operatorToken,
        },
        body,
      },
    );
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch {
    return Response.json({ detail: "ReclaimRail API is currently unavailable" }, { status: 503 });
  }
}
