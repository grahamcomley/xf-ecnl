# Sideline Standings iPhone app

A native shell (Capacitor 8) that loads https://sidelinestandings.com. Same setup as Hashmark.

- **Page changes need no app build.** The app shows the live site, so every "push to prod" is already in the app.
- **A new TestFlight build is needed only** when `capacitor.config.json`, `native/*`, `icon-1024.png` or `/codemagic.yaml` change.
  Start one from GitHub: Actions > Build iPhone app > Run workflow.
- **Alerts** come from Apple's push service (the app can't use web push). The page registers with
  `@capacitor/push-notifications` and sends the device token to `/api/push` as `apns:<token>`; the server
  sends with the Apple push key saved in Admin > App Store app (KV `cfg:apns`). The app's alert inbox and
  red-number count are kept by the server (`ib:<site>:<device>`), since there's no service worker receiving alerts.
- **Red number**: `native/SidelineApp.swift` (setBadge), registered by `native/AppViewController.swift`.
- **UAT inside the app**: Admin > App Store app > Switch this app to UAT (and back).
- Bundle ID `com.sidelinestandings.app`, Apple team `55FGL4DVG5`, shown on the home screen as "Sideline".
