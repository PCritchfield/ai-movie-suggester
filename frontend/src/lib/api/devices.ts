import { apiGet } from "./client";
import type { Device } from "./types";

export async function fetchDevices(): Promise<Device[]> {
  return apiGet<Device[]>("/api/devices");
}
