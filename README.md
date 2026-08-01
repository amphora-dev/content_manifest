# Amphora content manifest

Remote pin file for Amphora. The app fetches
`content_manifest.json` from this repository at runtime (no APK copy).

- **Runtime URL:** `https://raw.githubusercontent.com/amphora-dev/content_manifest/main/content_manifest.json`
- **Updated by:** `amphora-dev/imagefs` CI after each successful `amphora` Release publish (`components.rootfs` SHA / size / version).

## Validation

`validate_manifest.py` checks the invariants Amphora relies on at runtime, and
[`.github/workflows/validate.yml`](.github/workflows/validate.yml) runs it on
every push and pull request:

- every component carries a pinned 64-hex SHA-256 and a non-empty `version`
- non-`WCP` components carry an explicit `remoteUrl`; a `WCP` component without
  one has the `contentType` + `verName` that `RemoteUrlResolver` needs to look it
  up in `wcpCatalogUrl`
- all URLs are https, all sizes are positive
- `runtimeAssets[]` has no duplicate `assetPath`
- **a file pinned in both sections is pinned identically.**
  `graphics_driver/wrapper.tzst` appears as `components.turnip` *and* as a
  `runtimeAssets[]` entry; the two have drifted before, which leaves the app
  downloading one build and verifying it against the other build's digest.

Run it locally with `python3 validate_manifest.py` (no dependencies).
