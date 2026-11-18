import { NextRequest, NextResponse } from "next/server";

import {
  reviewerSessionCookieName,
  verifyReviewerSessionToken,
} from "@/lib/reviewer-session";

const PUBLIC_PATHS = new Set(["/access", "/api/reviewer/session"]);

export async function proxy(request: NextRequest): Promise<NextResponse> {
  const { pathname, search } = request.nextUrl;
  if (PUBLIC_PATHS.has(pathname)) return NextResponse.next();

  const authenticated = await verifyReviewerSessionToken(
    request.cookies.get(reviewerSessionCookieName())?.value,
  );
  if (authenticated) return NextResponse.next();

  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      { detail: "Reviewer session required" },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
  }

  const accessUrl = new URL("/access", request.url);
  const returnPath = `${pathname}${search}`;
  if (returnPath.startsWith("/") && !returnPath.startsWith("//")) {
    accessUrl.searchParams.set("next", returnPath);
  }
  return NextResponse.redirect(accessUrl);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
