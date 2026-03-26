import { cookies } from "next/headers";
import { getBaseUrl, parseResponse } from "./shared";

interface CookieReader {
  get(name: string): { value: string } | undefined;
}

export function buildCookieHeader(cookieReader: CookieReader): string {
  const session = cookieReader.get("session_id");
  return session ? `session_id=${session.value}` : "";
}

export async function serverGet<T>(path: string): Promise<T> {
  const cookieStore = await cookies();
  const cookieHeader = buildCookieHeader(cookieStore);

  const response = await fetch(`${getBaseUrl()}${path}`, {
    headers: {
      Cookie: cookieHeader,
      "Content-Type": "application/json",
    },
    cache: "no-store",
  });

  return parseResponse<T>(response);
}
