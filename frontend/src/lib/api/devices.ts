import { apiGet, apiPost } from "./client";
import {
  ApiAuthError,
  ApiError,
  DeviceOfflineError,
  PlaybackFailedError,
} from "./types";
import type { Device, PlayRequest, PlayResponse } from "./types";

export async function fetchDevices(): Promise<Device[]> {
  return apiGet<Device[]>("/api/devices");
}

/**
 * Dispatch a play command to a Jellyfin session.
 *
 * Error mapping (per backend/app/play/router.py contract):
 *   200 → PlayResponse
 *   401 → ApiAuthError (pass through; picker will call clearAuth + toast.error)
 *   409 → DeviceOfflineError (picker stays open, in-place refetch)
 *   500 / other → PlaybackFailedError (picker closes + toast.error)
 *
 * Goes through `apiPost` (not raw `fetch`) so the CSRF header + session
 * cookie are always attached. Do not bypass this — the backend enforces
 * CSRF on `/api/play` and a raw-fetch bypass would silently drop it.
 */
export async function postPlay(req: PlayRequest): Promise<PlayResponse> {
  try {
    return await apiPost<PlayResponse>("/api/play", req);
  } catch (err) {
    if (err instanceof ApiAuthError) {
      // Preserve auth errors as-is — T4 picker distinguishes this from
      // other failures to trigger the re-login flow.
      throw err;
    }
    if (err instanceof ApiError) {
      if (err.status === 409) {
        throw new DeviceOfflineError(err.body);
      }
      throw new PlaybackFailedError(err.status, err.body);
    }
    // NetworkError or anything else — classify as playback failure.
    throw err;
  }
}
