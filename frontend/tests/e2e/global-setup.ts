/**
 * Playwright globalSetup — Docker Compose orchestration, Jellyfin wizard,
 * test user provisioning, and storageState creation.
 *
 * If PLAYWRIGHT_BASE_URL is set, targets the existing server.
 * If unset, starts the Docker Compose stack and manages the full lifecycle.
 *
 * Credentials below are ephemeral test-environment values tied to the
 * disposable Jellyfin container in docker-compose.test.yml.  They are
 * NOT production secrets.  See backend/tests/integration/conftest.py for
 * the canonical Python counterparts.
 */

import { execSync } from "child_process";
import fs from "fs";
import path from "path";
import { request } from "@playwright/test";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PROJECT_ROOT = path.resolve(__dirname, "../../..");
const AUTH_DIR = path.resolve(__dirname, "../../.auth");
const ENV_FILE = path.join(AUTH_DIR, ".env.e2e");
const SENTINEL_FILE = path.join(AUTH_DIR, ".compose-started");
const STORAGE_STATE_PATH = path.join(AUTH_DIR, "state.json");

const COMPOSE_PROJECT = "ai-movie-suggester-e2e";

const JELLYFIN_URL = "http://localhost:8096";
const BACKEND_URL = "http://localhost:8000";
const FRONTEND_URL = "http://localhost:3000";

const POLL_INTERVAL_MS = 2_000;
const POLL_TIMEOUT_MS = 120_000;

const TEST_ADMIN_USER = "root";
const TEST_ADMIN_PASS = "test-admin-password";

const TEST_USERS = [
  { name: "test-alice", password: "test-alice-password" },
  { name: "test-bob", password: "test-bob-password" },
];

const AUTH_HEADER =
  'MediaBrowser Client="ai-movie-suggester-e2e", DeviceId="e2e-setup", Device="playwright", Version="0.0.0"';

// Test-only, deterministic secret — never use in production
const E2E_ENV_CONTENTS = [
  "SESSION_SECRET=e2e0a1b2c3d4e5f6a7b8c9d0e1f2a3b4",
  "SESSION_SECURE_COOKIE=false",
  "JELLYFIN_URL=http://jellyfin:8096",
  "CORS_ORIGIN=http://localhost:3000",
  "OLLAMA_HOST=http://localhost:11434",
  "LOG_LEVEL=debug",
].join("\n");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function authHeaders(token?: string): Record<string, string> {
  const value = token ? `${AUTH_HEADER}, Token=${token}` : AUTH_HEADER;
  return {
    Authorization: value,
    "Content-Type": "application/json",
  };
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollEndpoint(
  url: string,
  description: string,
  timeoutMs: number = POLL_TIMEOUT_MS,
): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const resp = await fetch(url);
      if (resp.ok) {
        console.log(`  [OK] ${description} ready at ${url}`);
        return;
      }
    } catch {
      // Service not ready yet
    }
    await sleep(POLL_INTERVAL_MS);
  }
  throw new Error(
    `Timed out waiting for ${description} at ${url} after ${timeoutMs / 1000}s`,
  );
}

// ---------------------------------------------------------------------------
// Docker Compose orchestration (Task 2.1)
// ---------------------------------------------------------------------------

function startDockerCompose(): void {
  console.log("Starting Docker Compose stack...");

  fs.mkdirSync(AUTH_DIR, { recursive: true });
  fs.writeFileSync(ENV_FILE, E2E_ENV_CONTENTS, "utf-8");

  execSync(
    [
      "docker compose",
      `-p ${COMPOSE_PROJECT}`,
      "-f docker-compose.yml",
      "-f docker-compose.test.yml",
      `--env-file ${ENV_FILE}`,
      "up -d",
    ].join(" "),
    { cwd: PROJECT_ROOT, stdio: "inherit" },
  );

  fs.writeFileSync(SENTINEL_FILE, new Date().toISOString(), "utf-8");
  console.log("Docker Compose stack started.");
}

// ---------------------------------------------------------------------------
// Health check polling (Task 2.2)
// ---------------------------------------------------------------------------

async function waitForServices(baseUrl?: string): Promise<void> {
  console.log("Waiting for services to be ready...");

  if (baseUrl) {
    // Only poll the provided base URL when targeting an existing server
    await pollEndpoint(baseUrl, "Frontend (existing server)");
  } else {
    // Poll all services in parallel — they boot concurrently via Compose
    await Promise.all([
      pollEndpoint(`${JELLYFIN_URL}/health`, "Jellyfin"),
      pollEndpoint(`${BACKEND_URL}/health`, "Backend"),
      pollEndpoint(FRONTEND_URL, "Frontend"),
    ]);
  }

  console.log("All services ready.");
}

// ---------------------------------------------------------------------------
// Jellyfin first-run wizard (Task 2.3)
// ---------------------------------------------------------------------------

async function completeJellyfinWizard(
  jellyfinUrl: string,
): Promise<string> {
  let adminUser = TEST_ADMIN_USER;

  // Step 1: Check if wizard needs completion
  const configResp = await fetch(`${jellyfinUrl}/Startup/Configuration`);
  if (configResp.status === 200) {
    console.log("Completing Jellyfin first-run wizard...");

    // Step 2: Discover admin username
    const userResp = await fetch(`${jellyfinUrl}/Startup/User`);
    if (userResp.ok) {
      const userData = (await userResp.json()) as { Name?: string };
      adminUser = userData.Name ?? TEST_ADMIN_USER;
    }

    // Step 3: Set configuration
    const configPostResp = await fetch(
      `${jellyfinUrl}/Startup/Configuration`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          UICulture: "en-US",
          MetadataCountryCode: "US",
          PreferredMetadataLanguage: "en",
        }),
      },
    );
    if (!configPostResp.ok) {
      throw new Error(
        `Failed to set startup configuration: ${configPostResp.status}`,
      );
    }

    // Step 4: Set admin user
    const adminSetResp = await fetch(`${jellyfinUrl}/Startup/User`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        Name: adminUser,
        Password: TEST_ADMIN_PASS,
      }),
    });
    if (!adminSetResp.ok) {
      throw new Error(
        `Failed to set admin user: ${adminSetResp.status}`,
      );
    }

    // Step 5: Remote access
    const remoteResp = await fetch(`${jellyfinUrl}/Startup/RemoteAccess`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        EnableRemoteAccess: true,
        EnableAutomaticPortMapping: false,
      }),
    });
    if (!remoteResp.ok) {
      throw new Error(
        `Failed to set remote access: ${remoteResp.status}`,
      );
    }

    // Step 6: Complete wizard
    const completeResp = await fetch(`${jellyfinUrl}/Startup/Complete`, {
      method: "POST",
    });
    if (!completeResp.ok) {
      throw new Error(
        `Failed to complete wizard: ${completeResp.status}`,
      );
    }

    console.log("Jellyfin wizard complete.");
  } else {
    console.log("Jellyfin wizard already completed, skipping.");
  }

  // Step 7: Authenticate as admin (retry loop).
  // Empty-password fallback is only safe against a fresh Compose-managed
  // Jellyfin — never attempt it against an existing server the user pointed
  // us at via PLAYWRIGHT_BASE_URL.
  const allowEmptyPassword = !process.env.PLAYWRIGHT_BASE_URL;
  const credentials: Array<{ username: string; password: string }> = [
    { username: adminUser, password: TEST_ADMIN_PASS },
    ...(allowEmptyPassword
      ? [{ username: adminUser, password: "" }]
      : []),
  ];

  const maxAttempts = 10;
  let lastStatus = 0;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    for (const cred of credentials) {
      const authResp = await fetch(
        `${jellyfinUrl}/Users/AuthenticateByName`,
        {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify({
            Username: cred.username,
            Pw: cred.password,
          }),
        },
      );
      lastStatus = authResp.status;

      if (authResp.ok) {
        const data = (await authResp.json()) as {
          AccessToken: string;
          User: { Id: string };
        };
        const token = data.AccessToken;

        // If we authenticated with an empty password, set the expected one
        if (cred.password !== TEST_ADMIN_PASS) {
          const pwResp = await fetch(
            `${jellyfinUrl}/Users/${data.User.Id}/Password`,
            {
              method: "POST",
              headers: authHeaders(token),
              body: JSON.stringify({
                CurrentPw: cred.password,
                NewPw: TEST_ADMIN_PASS,
              }),
            },
          );
          if (!pwResp.ok) {
            console.warn(
              `Warning: Could not set admin password (status ${pwResp.status})`,
            );
          }
        }

        console.log("Authenticated as admin.");
        return token;
      }
    }

    if (attempt < maxAttempts - 1) {
      await sleep(3_000);
    }
  }

  throw new Error(
    `Cannot authenticate as ${adminUser} after ${maxAttempts} attempts (last status: ${lastStatus})`,
  );
}

// ---------------------------------------------------------------------------
// Test user provisioning (Task 2.4)
// ---------------------------------------------------------------------------

async function provisionTestUsers(
  jellyfinUrl: string,
  adminToken: string,
): Promise<void> {
  console.log("Provisioning test users...");

  const usersResp = await fetch(`${jellyfinUrl}/Users`, {
    headers: authHeaders(adminToken),
  });
  if (!usersResp.ok) {
    throw new Error(`Failed to list users: ${usersResp.status}`);
  }

  const existingUsers = (await usersResp.json()) as Array<{
    Name: string;
    Id: string;
  }>;
  const existingNames = new Set(existingUsers.map((u) => u.Name));

  for (const user of TEST_USERS) {
    if (existingNames.has(user.name)) {
      console.log(`  User "${user.name}" already exists, skipping.`);
      continue;
    }

    const createResp = await fetch(`${jellyfinUrl}/Users/New`, {
      method: "POST",
      headers: authHeaders(adminToken),
      body: JSON.stringify({
        Name: user.name,
        Password: user.password,
      }),
    });
    if (!createResp.ok) {
      throw new Error(
        `Failed to create user "${user.name}": ${createResp.status}`,
      );
    }
    console.log(`  Created user "${user.name}".`);
  }

  console.log("Test users provisioned.");
}

// ---------------------------------------------------------------------------
// storageState creation (Task 2.5)
// ---------------------------------------------------------------------------

async function createStorageState(baseUrl: string): Promise<void> {
  console.log("Creating storageState via programmatic login...");

  const context = await request.newContext({ baseURL: baseUrl });

  const resp = await context.post("/api/auth/login", {
    data: {
      username: TEST_USERS[0].name,
      password: TEST_USERS[0].password,
    },
  });

  if (!resp.ok()) {
    throw new Error(
      `Programmatic login failed: ${resp.status()} ${resp.statusText()}`,
    );
  }

  fs.mkdirSync(AUTH_DIR, { recursive: true });
  await context.storageState({ path: STORAGE_STATE_PATH });
  await context.dispose();

  console.log(`storageState saved to ${STORAGE_STATE_PATH}`);
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export default async function globalSetup(): Promise<void> {
  const existingBaseUrl = process.env.PLAYWRIGHT_BASE_URL;

  if (existingBaseUrl) {
    console.log(`Using existing server at ${existingBaseUrl}`);
    await waitForServices(existingBaseUrl);
  } else {
    startDockerCompose();
    await waitForServices();

    // Complete wizard and provision users against Jellyfin on localhost
    const adminToken = await completeJellyfinWizard(JELLYFIN_URL);
    await provisionTestUsers(JELLYFIN_URL, adminToken);
  }

  // Create storageState for authenticated tests
  const baseUrl = existingBaseUrl ?? FRONTEND_URL;
  await createStorageState(baseUrl);
}
