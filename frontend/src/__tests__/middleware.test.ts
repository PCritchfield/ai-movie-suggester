import { describe, it, expect } from "vitest";
import { NextRequest } from "next/server";
import { middleware, config } from "../middleware";

function makeRequest(url: string, cookies?: Record<string, string>) {
  const req = new NextRequest(new URL(url, "http://localhost:3000"));
  if (cookies) {
    for (const [key, value] of Object.entries(cookies)) {
      req.cookies.set(key, value);
    }
  }
  return req;
}

describe("middleware", () => {
  it("redirects to /login when no session_id cookie", () => {
    const req = makeRequest("/");
    const res = middleware(req);
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://localhost:3000/login");
  });

  it("passes through when session_id cookie exists", () => {
    const req = makeRequest("/", { session_id: "abc123" });
    const res = middleware(req);
    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
  });
});

describe("config.matcher", () => {
  it("excludes login, api, and static assets", () => {
    const pattern = config.matcher[0];
    expect(pattern).toContain("login");
    expect(pattern).toContain("api");
    expect(pattern).toContain("_next/static");
    expect(pattern).toContain("_next/image");
    expect(pattern).toContain("favicon.ico");
  });
});
