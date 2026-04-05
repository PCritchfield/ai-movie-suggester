import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest): NextResponse {
  const session = request.cookies.get("session_id");
  if (!session) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!login|api|_next/static|_next/image|favicon\\.ico|manifest\\.webmanifest|icons/|sw\\.js|offline\\.html).*)",
  ],
};
