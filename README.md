# Amphora content manifest

Remote pin file for Amphora. The app fetches
`content_manifest.json` from this repository at runtime (no APK copy).

- **Runtime URL:** `https://raw.githubusercontent.com/amphora-dev/content_manifest/main/content_manifest.json`
- **Updated by:** `amphora-dev/imagefs` CI after each successful Release publish (`components.rootfs`, `components.box64`, and the `runtimeAssets[]` entry for `graphics_driver/wrapper.tzst`).

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

Run it locally with `python3 validate_manifest.py` (no dependencies).
