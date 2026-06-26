import { twMerge } from "tailwind-merge";

// All call sites pass plain class strings (no clsx conditional-object syntax),
// so twMerge alone covers merge + dedupe — clsx was redundant indirection.
export const cn = twMerge;
