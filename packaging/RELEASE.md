# Release-Prozess — Parakeet Dictate (signiertes, notarisiertes DMG)

Ziel: ein `.dmg`, das Endnutzer per Doppelklick installieren — ohne Gatekeeper-Warnung.

## Voraussetzungen (einmalig)

1. **Apple Developer Program** (99 $/Jahr).
2. **„Developer ID Application"-Zertifikat** im Login-Keychain. Prüfen:
   ```bash
   security find-identity -v -p codesigning
   ```
   Du brauchst die Zeile `Developer ID Application: DEIN NAME (TEAMID)`.
   (Fehlt es: in Xcode → Settings → Accounts → Manage Certificates → „+" → Developer ID Application.)
3. **Notarytool-Profil** anlegen (speichert den Zugang sicher im Keychain):
   ```bash
   xcrun notarytool store-credentials parakeet-notary \
     --apple-id "DEINE_APPLE_ID" \
     --team-id "DEINE_TEAM_ID" \
     --password "APP-SPEZIFISCHES-PASSWORT"
   ```
   Das **App-spezifische Passwort** erzeugst du auf
   appleid.apple.com → „Anmeldung & Sicherheit" → App-spezifische Passwörter.

## Lokal bauen & veröffentlichen

```bash
# 1) App bauen (Icon + PyInstaller-Bundle)
./packaging/build_app.sh

# 2) Signieren + notarisieren + DMG
#    IDENTITY anpassen (oder als Env-Var übergeben):
IDENTITY="Developer ID Application: DEIN NAME (TEAMID)" ./packaging/sign_notarize_dmg.sh
```

Ergebnis: `dist/ParakeetDictate.dmg` (signiert, notarisiert, gestapelt). Diese Datei als
GitHub-Release-Asset hochladen — fertig für Endnutzer.

## Automatisch via GitHub Actions

`.github/workflows/release.yml` baut + signiert + notarisiert bei jedem `v*`-Tag und hängt
das DMG an den Release. Benötigte Repository-Secrets:

| Secret | Inhalt |
|---|---|
| `MACOS_CERT_P12_BASE64` | `base64 -i DeveloperID.p12` (Zertifikat als .p12 exportiert) |
| `MACOS_CERT_PASSWORD` | Passwort des .p12-Exports |
| `MACOS_SIGN_IDENTITY` | `Developer ID Application: … (TEAMID)` |
| `NOTARY_APPLE_ID` | deine Apple-ID |
| `NOTARY_TEAM_ID` | deine Team-ID |
| `NOTARY_PASSWORD` | App-spezifisches Passwort |

Release auslösen:
```bash
git tag v1.0.0 && git push origin v1.0.0
```

## Versionierung

Beim Hochziehen die Version an drei Stellen in `packaging/ParakeetDictate.spec` ändern:
`version`, `CFBundleShortVersionString`, `CFBundleVersion`.

## Hinweise / Stolpersteine

- **Hardened Runtime + numba/llvmlite:** Die App braucht die JIT-Entitlements in
  `packaging/entitlements.plist` (`allow-jit`, `allow-unsigned-executable-memory`,
  `disable-library-validation`). Ohne sie stürzt die notarisierte App beim Modell-Laden ab.
- **Nur Apple Silicon:** Das Bundle ist `arm64` (MLX/Metal). Kein Intel-Build.
- **Modell wird nicht gebündelt:** Endnutzer laden es beim ersten Start (~1–2 GB) aus dem
  HuggingFace-Cache. Das DMG bleibt dadurch klein(er).
- **Erststart-Dauer:** Beim allerersten Öffnen scannt macOS das Bundle einmalig
  (einige Sekunden). Danach startet die App schnell.
