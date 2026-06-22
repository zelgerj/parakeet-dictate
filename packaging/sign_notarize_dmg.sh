#!/usr/bin/env bash
# Signs the app with a Developer ID, builds a DMG, notarizes and staples it.
#
# PREREQUISITES (one-time, see packaging/RELEASE.md):
#   1) "Developer ID Application" certificate in the login keychain:
#        security find-identity -v -p codesigning
#   2) Create a notarytool profile (stores the credentials securely in the keychain):
#        xcrun notarytool store-credentials parakeet-notary \
#          --apple-id "YOUR_APPLE_ID" --team-id "YOUR_TEAM_ID" \
#          --password "APP-SPECIFIC-PASSWORD"
#
# Usage (from the repo root), after build_app.sh has run:
#   IDENTITY="Developer ID Application: YOUR NAME (TEAMID)" ./packaging/sign_notarize_dmg.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# ─── Adjust here (or pass as an env var) ─────────────────────────────────────
IDENTITY="${IDENTITY:-Developer ID Application: Johann Zelger (CS72WV49JK)}"
NOTARY_PROFILE="${NOTARY_PROFILE:-parakeet-notary}"
# ─────────────────────────────────────────────────────────────────────────────

APP="dist/Parakeet Dictate.app"
DMG="dist/ParakeetDictate.dmg"
ENTITLEMENTS="packaging/entitlements.plist"

[ -d "$APP" ] || { echo "ERROR: $APP missing — run ./packaging/build_app.sh first."; exit 1; }

echo "==> Signing nested libraries (.dylib/.so)"
find "$APP/Contents" -type f \( -name "*.dylib" -o -name "*.so" \) -print0 \
  | while IFS= read -r -d '' f; do
      codesign --force --timestamp --options runtime --sign "$IDENTITY" "$f"
    done

echo "==> Signing the app (entitlements + hardened runtime)"
codesign --force --timestamp --options runtime \
  --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" "$APP"

echo "==> Verifying signature"
codesign --verify --deep --strict --verbose=2 "$APP"

# Notarize + staple the .app ITSELF (before the DMG) so the self-updater can verify the
# downloaded app's notarization OFFLINE via spctl. This is a second notarytool submission.
echo "==> Notarizing + stapling the .app (offline-verifiable updates)"
APP_ZIP="dist/_ParakeetDictate-app.zip"
rm -f "$APP_ZIP"
ditto -c -k --keepParent "$APP" "$APP_ZIP"
xcrun notarytool submit "$APP_ZIP" --keychain-profile "$NOTARY_PROFILE" --wait
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"
rm -f "$APP_ZIP"

echo "==> Building DMG (with an Applications shortcut for drag & drop)"
rm -f "$DMG"
STAGING="$(mktemp -d)"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
hdiutil create -volname "Parakeet Dictate" -srcfolder "$STAGING" -ov -format UDZO "$DMG"
rm -rf "$STAGING"
codesign --force --timestamp --sign "$IDENTITY" "$DMG"

echo "==> Notarizing (may take a few minutes) ..."
xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait

echo "==> Stapling the notarization ticket onto the DMG"
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"

echo "==> Gatekeeper check"
spctl -a -t open --context context:primary-signature -vvv "$DMG" || true

echo "==> DONE: $DMG  (signed, notarized, stapled — ready to distribute)"
