/**
 * Playwright globalTeardown — tears down Docker Compose services
 * (if started by globalSetup) and cleans up temporary files.
 */

import { execSync } from "child_process";
import fs from "fs";
import path from "path";

const PROJECT_ROOT = path.resolve(__dirname, "../../..");
const AUTH_DIR = path.resolve(__dirname, "../../.auth");
const SENTINEL_FILE = path.join(AUTH_DIR, ".compose-started");
const COMPOSE_PROJECT = "ai-movie-suggester-e2e";

export default async function globalTeardown(): Promise<void> {
  // Tear down Docker Compose if globalSetup started it
  if (fs.existsSync(SENTINEL_FILE)) {
    console.log("Tearing down Docker Compose stack...");
    try {
      execSync(
        [
          "docker compose",
          `-p ${COMPOSE_PROJECT}`,
          "-f docker-compose.yml",
          "-f docker-compose.test.yml",
          "down -v",
        ].join(" "),
        { cwd: PROJECT_ROOT, stdio: "inherit" },
      );
      console.log("Docker Compose stack torn down.");
    } catch (err) {
      console.warn("Warning: Docker Compose teardown failed:", err);
    }
  }

  // Clean up .auth/ directory (state.json, .env.e2e, sentinel)
  if (fs.existsSync(AUTH_DIR)) {
    fs.rmSync(AUTH_DIR, { recursive: true, force: true });
    console.log("Cleaned up .auth/ directory.");
  }
}
