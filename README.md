# Amphora content manifest

Remote pin file for Amphora. The app fetches
`content_manifest.json` from this repository at runtime (no APK copy).

- **Runtime URL (preferred):**
  `https://api.github.com/repos/amphora-dev/content_manifest/contents/content_manifest.json?ref=main`
- **Fallback:** GitHub raw `main`. The Contents API is preferred because raw/CDN
  branch content can remain cached after a pin update. Development devices may
  retry on transient API failures or rate limiting.
- **Updated by:** `amphora-dev/imagefs` CI after each successful Release publish
  (`components.rootfs`, `components.box64`, and the `runtimeAssets[]` entry for
  `graphics_driver/wrapper.tzst`).

## App update pin

`app_update.json` is the APK auto-update pin (versionCode / apkUrl / sha256).
Amphora CI on `main` publishes `amphora-debug.apk` to the rolling Release tag
`apk` on `amphora-dev/amphora`, then writes this file. Runtime URL:

`https://api.github.com/repos/amphora-dev/content_manifest/contents/app_update.json?ref=main`

## Validation

On every `main` push that changes `content_manifest.json` or `app_update.json`,
[`.github/workflows/validate.yml`](.github/workflows/validate.yml) validates the
manifest and app-update pin. It does not create tags or publish/purge CDN state.

## Two sections, one home per file

- `components[]` — resolved by `ContentSource`; the keys are Amphora's
  `ContentComponent` enum (`rootfs`, `wine`, `box64`, `dxvk`, `vkd3d`).
- `runtimeAssets[]` — kernel-direct files that `RuntimeAssetProvisioner` places
  under `filesDir/runtime-assets/<assetPath>`.

A file belongs to exactly one of them. `graphics_driver/wrapper.tzst` was in
both, and the copies drifted — the app then downloaded one wrapper build and
verified it against the other build's digest.

## Validation

`validate_manifest.py` checks the invariants Amphora relies on at runtime, and
[`.github/workflows/validate.yml`](.github/workflows/validate.yml) runs it on
every push and pull request:

- `components[]` is exactly the set Amphora's `ContentComponent` enum knows. The
  app skips keys it does not recognise (so that adding one cannot brick
  installed builds), which means a typo is silent on the device and has to be
  caught here
- every component carries a pinned 64-hex SHA-256 and a non-empty `version`
- non-`WCP` components carry an explicit `remoteUrl`; a `WCP` component without
  one has the `contentType` + `verName` that `RemoteUrlResolver` needs to look it
  up in `wcpCatalogUrl`
- all URLs are https, all sizes are positive
- `runtimeAssets[]` has no duplicate `assetPath`
- a file pinned in both sections is pinned identically — a backstop in case the
  wrapper-style duplication is ever reintroduced
- every `WCP` pin has `contentType` + `verName` + `verCode`, and `version` equals
  `{contentType}-{verName}-{verCode}` (the on-device install directory name). A
  mismatch is why the UI shows permanent “Update needed” after a rebuild
- with `VALIDATE_FETCH_WCP=1`, each WCP is downloaded and its embedded
  `profile.json` must match those fields plus the sha/size pin

Run it locally with `python3 validate_manifest.py` (no dependencies for the
offline checks). Profile fetch needs the `zstandard` package.

## Pinning a rebuilt WCP

Rebuilds must bump the pin from the package itself, not hand-edit verCode:

```bash
eval "$(python3 pin_from_wcp.py ./Proton-11.0-amphora-x86_64.wcp)"
COMPONENT=wine ASSET_PATH="$ASSET_PATH" REMOTE_URL="https://…" \
  ./path/to/imagefs/ci/publish/bump-manifest.sh
```

`pin_from_wcp.py` prints `VER_NAME` / `VER_CODE` / `CONTENT_TYPE` / `SHA256` /
`SIZE` from `profile.json` so bump-manifest stays idempotent across rebuilds.
