/**
 * Structured chat output E2E (Spec 27, version-2 SSE contract).
 *
 * Asserts the FRONTEND consumption of the v2 stream through a real browser:
 *   - the staged status sequence renders IN ORDER
 *     (loading → "Searching your library…" → "Thinking about your picks…"
 *      → response with picks + prose together),
 *   - the two-section layout ("Recommended" + collapsed "More matches"),
 *   - the "Show more" disclosure reveals the remaining candidates,
 *   - the canned fallback path (no picks) renders without a "Recommended" section.
 *
 * Design decision (recorded in the task file per the audit FLAG on 5.1):
 * the /api/chat SSE response is mocked client-side via an injected window.fetch
 * override that emits frames on a TIMED schedule. This is deliberate:
 *   1. It makes the staged status sequence deterministic and observable —
 *      Playwright cannot reliably catch a sub-millisecond "generating" flash if
 *      the whole SSE body is delivered at once (route.fulfill has no streaming).
 *   2. It lets us force the fallback (zero-valid-picks) path the live harness
 *      cannot otherwise force — the audit's preferred remediation.
 * Backend behaviour (search → structured generation → ID validation → fallback)
 * is covered by the backend suite + the 2.6 router test; this spec owns the
 * browser-level v2 contract consumption only.
 *
 * The auth/session and app shell are real (storageState from globalSetup);
 * only the POST /api/chat stream is synthesized.
 */

import type { Page } from "@playwright/test";
import { test, expect } from "../fixtures/auth.fixture";
import type { SSEEvent, SearchResultItem } from "../../../src/lib/api/types";

// ---------------------------------------------------------------------------
// Mock scenario shape — plain serialisable data passed into addInitScript.
// ---------------------------------------------------------------------------

interface MockStep {
  /** Delay (ms) added to the running clock before this frame is enqueued. */
  delayMs: number;
  /** SSE event to emit at this point in the schedule. */
  event: SSEEvent;
}

interface MockScenario {
  steps: MockStep[];
}

// ---------------------------------------------------------------------------
// Fixture data
// ---------------------------------------------------------------------------

function makeCandidate(index: number): SearchResultItem {
  return {
    jellyfin_id: `mock-${index}`,
    title: `Mock Movie ${index}`,
    overview: `Overview for mock movie ${index}.`,
    genres: ["Drama"],
    year: 2000 + index,
    score: 1 - index * 0.05,
    poster_url: "",
    community_rating: null,
    runtime_minutes: 100 + index,
    jellyfin_web_url: null,
  };
}

const CANDIDATES: SearchResultItem[] = Array.from({ length: 5 }, (_, i) =>
  makeCandidate(i + 1)
);

const SUCCESS_PROSE =
  "Based on your taste, these two should land well together.";
const CANNED_FALLBACK =
  "I could not find a confident match in your library for that. Try rephrasing?";

/**
 * Success scenario: metadata → status(generating) → picks → text → done.
 * The model "picks" the first two candidates, leaving three under "More matches".
 * Timing is spaced so each staged status phase is comfortably observable.
 */
const SUCCESS_SCENARIO: MockScenario = {
  steps: [
    // ~900ms of "Searching your library…" before search results land.
    {
      delayMs: 900,
      event: {
        type: "metadata",
        version: 2,
        recommendations: CANDIDATES,
        search_status: "ok",
        turn_count: 1,
      },
    },
    // Same tick: generation begins → "Thinking about your picks…".
    { delayMs: 0, event: { type: "status", phase: "generating" } },
    // ~900ms of "Thinking…" before the structured result is validated.
    {
      delayMs: 900,
      event: {
        type: "picks",
        version: 2,
        picks: [
          {
            jellyfin_id: "mock-1",
            reasoning: "Tense and character-driven.",
            pick_order: 1,
          },
          {
            jellyfin_id: "mock-2",
            reasoning: "A funnier companion piece.",
            pick_order: 2,
          },
        ],
      },
    },
    { delayMs: 30, event: { type: "text", content: SUCCESS_PROSE } },
    { delayMs: 30, event: { type: "done" } },
  ],
};

/**
 * Fallback scenario: all model picks were hallucinated IDs, so the backend
 * drops them and emits a canned message with NO picks event.
 */
const FALLBACK_SCENARIO: MockScenario = {
  steps: [
    {
      delayMs: 900,
      event: {
        type: "metadata",
        version: 2,
        recommendations: CANDIDATES,
        search_status: "ok",
        turn_count: 1,
      },
    },
    { delayMs: 0, event: { type: "status", phase: "generating" } },
    { delayMs: 900, event: { type: "text", content: CANNED_FALLBACK } },
    { delayMs: 30, event: { type: "done" } },
  ],
};

// ---------------------------------------------------------------------------
// Client-side fetch override (runs in the browser before app scripts).
// ---------------------------------------------------------------------------

/**
 * Installed via addInitScript. Replaces window.fetch so that a POST to
 * /api/chat returns a synthetic text/event-stream Response whose body is
 * enqueued frame-by-frame on the scenario's timed schedule. All other
 * requests (auth, history) fall through to the real fetch.
 */
function installChatStreamMock(scenario: MockScenario): void {
  const originalFetch = window.fetch.bind(window);
  const encoder = new TextEncoder();

  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const method = (
      init?.method ?? (input instanceof Request ? input.method : "GET")
    ).toUpperCase();

    const isChatPost =
      method === "POST" &&
      url.includes("/api/chat") &&
      !url.includes("/history");

    if (!isChatPost) {
      return originalFetch(input, init);
    }

    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        let clock = 0;
        for (const step of scenario.steps) {
          clock += step.delayMs;
          const frame = step.event;
          setTimeout(() => {
            controller.enqueue(
              encoder.encode(`data: ${JSON.stringify(frame)}\n\n`)
            );
          }, clock);
        }
        setTimeout(() => controller.close(), clock + 20);
      },
    });

    return Promise.resolve(
      new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      })
    );
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function sendChat(page: Page, scenario: MockScenario): Promise<void> {
  await page.addInitScript(installChatStreamMock, scenario);
  // Mobile-first viewport — the layout this PR targets (and the 4.7 screenshots).
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const input = page.getByLabel("Chat message");
  await expect(input).toBeVisible();
  await input.fill("Something like Alien but funny");
  await page.getByRole("button", { name: "Send message" }).click();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Structured chat output (v2 SSE)", () => {
  test("renders the staged status sequence in order, then picks + prose together, then 'Show more'", async ({
    authenticatedPage: page,
  }, testInfo) => {
    await sendChat(page, SUCCESS_SCENARIO);

    const searching = page.getByText("Searching your library…");
    const thinking = page.getByText("Thinking about your picks…");

    // 1) Staged status — IN ORDER. "Searching…" is visible while
    //    "Thinking…" has NOT yet appeared — this proves the ORDER, not just
    //    that both labels eventually rendered (toBeHidden resolves the instant
    //    the element is absent, so it asserts the current frame, not a wait).
    await expect(searching).toBeVisible();
    await expect(thinking).toBeHidden();

    // 2) …then transitions to "Thinking about your picks…" (and "Searching…"
    //    is gone — proving a real transition, not two overlapping labels).
    await expect(thinking).toBeVisible();
    await expect(searching).toBeHidden();

    // 3) Final response — prose AND the "Recommended" picks section arrive
    //    together (the core v2 behaviour). Status labels are gone.
    await expect(page.getByText(SUCCESS_PROSE)).toBeVisible();
    await expect(thinking).toBeHidden();

    const recommendedLabel = page.getByText("Recommended", { exact: true });
    await expect(recommendedLabel).toBeVisible();

    // Picks render in LLM order, badged.
    await expect(
      page.getByRole("button", {
        name: /Recommended pick: View details for Mock Movie 1/,
      })
    ).toBeVisible();
    await expect(
      page.getByRole("button", {
        name: /Recommended pick: View details for Mock Movie 2/,
      })
    ).toBeVisible();

    // 4) "More matches" disclosure — collapsed by default, holds the remaining
    //    3 candidates (5 total − 2 picks).
    const moreMatches = page.getByText(/More matches \(3\)/);
    await expect(moreMatches).toBeVisible();

    // Screenshot (Task 4.7): mobile, two-section layout, disclosure collapsed.
    // testInfo.outputPath namespaces by project (chromium/firefox) + retry, so
    // parallel projects never collide on a shared filename.
    await page.screenshot({
      path: testInfo.outputPath("spec27-mobile-recommended-collapsed.png"),
      fullPage: true,
    });

    // Reveal the remaining candidates and confirm one becomes visible.
    await moreMatches.click();
    await expect(
      page.getByRole("button", { name: /View details for Mock Movie 5/ })
    ).toBeVisible();

    // Screenshot (Task 4.7): mobile, "More matches" expanded.
    await page.screenshot({
      path: testInfo.outputPath("spec27-mobile-more-matches-expanded.png"),
      fullPage: true,
    });
  });

  test("fallback path: canned message renders with no 'Recommended' section", async ({
    authenticatedPage: page,
  }) => {
    await sendChat(page, FALLBACK_SCENARIO);

    // Staged status still runs.
    await expect(page.getByText("Searching your library…")).toBeVisible();
    await expect(page.getByText("Thinking about your picks…")).toBeVisible();

    // Canned message renders…
    await expect(page.getByText(CANNED_FALLBACK)).toBeVisible();

    // …and there is NO picks section (no "Recommended" label, no disclosure).
    await expect(page.getByText("Recommended", { exact: true })).toHaveCount(0);
    await expect(page.getByText(/More matches/)).toHaveCount(0);
  });
});
