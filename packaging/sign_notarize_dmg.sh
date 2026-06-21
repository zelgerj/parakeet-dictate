#!/usr/bin/env bash
# Signiert die App mit Developer ID, baut ein DMG, notarisiert und stapelt es.
#
# VORAUSSETZUNGEN (einmalig, siehe packaging/RELEASE.md):
#   1) "Developer ID Application"-Zertifikat im Login-Keychain:
#        security find-identity -v -p codesigning
#   2) Notarytool-Profil anlegen (speichert Zugang sicher im Keychain):
#        xcrun notarytool store-credentials parakeet-notary \
#          --apple-id "DEINE_APPLE_ID" --team-id "DEINE_TEAM_ID" \
#          --password "APP-SPEZIFISCHES-PASSWORT"
#
# Nutzung (aus der Repo-Wurzel), nachdem build_app.sh gelaufen ist:
#   IDENTITY="Developer ID Application: DEIN NAME (TEAMID)" ./packaging/sign_notarize_dmg.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# ─── HIER anpassen (oder als Env-Var übergeben) ──────────────────────────────
IDENTITY="${IDENTITY:-Developer ID Application: Johann Zelger (CS72WV49JK)}"
NOTARY_PROFILE="${NOTARY_PROFILE:-parakeet-notary}"
# ─────────────────────────────────────────────────────────────────────────────

APP="dist/Parakeet Dictate.app"
DMG="dist/ParakeetDictate.dmg"
ENTITLEMENTS="packaging/entitlements.plist"

[ -d "$APP" ] || { echo "FEHLER: $APP fehlt — zuerst ./packaging/build_app.sh ausführen."; exit 1; }

echo "==> Signiere verschachtelte Bibliotheken (.dylib/.so)"
find "$APP/Contents" -type f \( -name "*.dylib" -o -name "*.so" \) -print0 \
  | while IFS= read -r -d '' f; do
      codesign --force --timestamp --options runtime --sign "$IDENTITY" "$f"
    done

echo "==> Signiere die App (Entitlements + Hardened Runtime)"
codesign --force --timestamp --options runtime \
  --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" "$APP"

echo "==> Prüfe Signatur"
codesign --verify --deep --strict --verbose=2 "$APP"

echo "==> Baue DMG (mit Programme-Verknüpfung für Drag&Drop)"
rm -f "$DMG"
STAGING="$(mktemp -d)"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
hdiutil create -volname "Parakeet Dictate" -srcfolder "$STAGING" -ov -format UDZO "$DMG"
rm -rf "$STAGING"
codesign --force --timestamp --sign "$IDENTITY" "$DMG"

echo "==> Notarisiere (kann einige Minuten dauern) ..."
xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait

echo "==> Stemple das Notarisierungs-Ticket auf das DMG"
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"

echo "==> Gatekeeper-Check"
spctl -a -t open --context context:primary-signature -vvv "$DMG" || true

echo "==> FERTIG: $DMG  (signiert, notarisiert, gestapelt — bereit zum Verteilen)"
