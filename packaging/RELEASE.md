# Release process — Parakeet Dictate (signed, notarized DMG)

Goal: a `.dmg` that end users install by double-clicking — without a Gatekeeper warning.

## Prerequisites (one-time)

1. **Apple Developer Program** ($99/year).
2. A **"Developer ID Application" certificate** in the login keychain. Check:
   ```bash
   security find-identity -v -p codesigning
   ```
   You need the line `Developer ID Application: YOUR NAME (TEAMID)`.
   (Missing it? Xcode → Settings → Accounts → Manage Certificates → "+" → Developer ID Application.)
3. A **notarytool profile** (stores the credentials securely in the keychain):
   ```bash
   xcrun notarytool store-credentials parakeet-notary \
     --apple-id "YOUR_APPLE_ID" \
     --team-id "YOUR_TEAM_ID" \
     --password "APP-SPECIFIC-PASSWORD"
   ```
   Create the **app-specific password** at
   appleid.apple.com → "Sign-In and Security" → App-Specific Passwords.

## Build & publish locally

```bash
# 1. Build the app (icon + PyInstaller bundle)
./packaging/build_app.sh

# 2. Sign + notarize + DMG
#    Adjust IDENTITY (or pass it as an env var):
IDENTITY="Developer ID Application: YOUR NAME (TEAMID)" ./packaging/sign_notarize_dmg.sh
```

Result: `dist/ParakeetDictate.dmg` (signed, notarized, stapled). Upload this file as a
GitHub release asset — ready for end users.

## Automatically via GitHub Actions

`.github/workflows/release.yml` builds + signs + notarizes on every `v*` tag and
attaches the DMG to the release. Required repository secrets:

| Secret | Contents |
|---|---|
| `MACOS_CERT_P12_BASE64` | `base64 -i DeveloperID.p12` (certificate exported as .p12) |
| `MACOS_CERT_PASSWORD` | password of the .p12 export |
| `MACOS_SIGN_IDENTITY` | `Developer ID Application: … (TEAMID)` |
| `NOTARY_APPLE_ID` | your Apple ID |
| `NOTARY_TEAM_ID` | your Team ID |
| `NOTARY_PASSWORD` | app-specific password |

Trigger a release:
```bash
git tag v1.0.0 && git push origin v1.0.0
```

## Versioning

When bumping the version, change it in three places in `packaging/ParakeetDictate.spec`:
`version`, `CFBundleShortVersionString`, `CFBundleVersion`.

## Notes / gotchas

- **Hardened Runtime + microphone:** the app needs `com.apple.security.device.audio-input`
  in `packaging/entitlements.plist`. Without it the notarized app is blocked from the
  microphone and never even appears in the Microphone list in System Settings.
- **Hardened Runtime + numba/llvmlite:** needs the JIT entitlements (`allow-jit`,
  `allow-unsigned-executable-memory`, `disable-library-validation`). Without them the
  notarized app crashes when loading the model.
- **Apple Silicon only:** the bundle is `arm64` (MLX/Metal). No Intel build.
- **The model is not bundled:** end users download it on first launch (~1–2 GB) into the
  HuggingFace cache, keeping the DMG smaller.
- **First-launch time:** on the very first open macOS scans the bundle once (a few
  seconds). After that the app starts quickly.
- **TCC permissions and rebuilds:** permissions granted via the native prompts are bound
  to the code signature (Developer ID), so they survive rebuilds with the same
  certificate. After granting Input Monitoring / Accessibility, restart the app once.
