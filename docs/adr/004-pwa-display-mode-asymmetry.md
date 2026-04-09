# ADR 004: PWA Display Mode Asymmetry (iOS vs Android)

**Status:** Accepted
**Date:** 2026-04-09
**Context:** Spec 14 (PWA Setup)

## Decision

The PWA uses different effective display modes on iOS and Android:

- **Manifest** (`manifest.webmanifest`): `"display": "minimal-ui"` -- Android respects this and shows browser chrome (back button, reload).
- **Layout metadata** (`layout.tsx`): `appleWebApp.capable: true` -- iOS interprets this as a request for standalone mode (no browser chrome).

This means Android users get `minimal-ui` and iOS users get `standalone`.

## Why

- **iOS:** Users who add a PWA to their home screen expect a standalone app experience. Safari ignores `minimal-ui` entirely and treats it as `browser`, which defeats the purpose of installation. Setting `apple-mobile-web-app-capable: yes` is the only way to get an app-like experience on iOS.
- **Android:** `minimal-ui` provides a native-feeling back button and reload control that the app does not replicate in its own UI. This is more useful than standalone for a single-page chat interface where browser navigation aids are helpful.

## Consequences

- Cross-platform testing must account for the different chrome: iOS has no system back/reload; Android does.
- If the app adds its own navigation controls (e.g., a back button in the chat header), the Android display mode could be reconsidered.
- The `useInstallPrompt` hook already checks for both `standalone` and `minimal-ui` display modes when detecting whether the app is installed.
