export function requestHasSameOrigin(request: Request): boolean {
  const originHeader = request.headers.get("origin");
  const host = (
    request.headers.get("x-forwarded-host") ?? request.headers.get("host")
  )
    ?.split(",")[0]
    ?.trim();
  const protocol = (
    request.headers.get("x-forwarded-proto") ??
    new URL(request.url).protocol.replace(":", "")
  )
    .split(",")[0]
    ?.trim();
  if (!originHeader || !host || !protocol) return false;

  try {
    const origin = new URL(originHeader);
    return origin.host === host && origin.protocol === `${protocol}:`;
  } catch {
    return false;
  }
}
