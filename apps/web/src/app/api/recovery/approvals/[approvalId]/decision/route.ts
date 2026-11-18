import { cookies } from "next/headers";

import {
  reviewerSessionCookieName,
  verifyReviewerSessionToken,
} from "@/lib/reviewer-session";
import { requestHasSameOrigin } from "@/lib/same-origin";

const MAX_REQUEST_BYTES = 4096;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function apiBaseUrl(): string {
  return (
    process.env.RECLAIMRAIL_API_BASE_URL?.replace(/\/$/, "") ??
    "http://127.0.0.1:8000"
  );
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ approvalId: string }> },
): Promise<Response> {
  if (!requestHasSameOrigin(request)) {
    return Response.json({ detail: "Reviewer access denied" }, { status: 403 });
  }
  const cookieStore = await cookies();
  const authenticated = await verifyReviewerSessionToken(
    cookieStore.get(reviewerSessionCookieName())?.value,
  );
  if (!authenticated) {
    return Response.json({ detail: "Reviewer access denied" }, { status: 401 });
  }

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
