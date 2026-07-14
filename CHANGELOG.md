# Changelog

All notable Hermes Agency product changes are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Keryx primary transport integration through `agency.transport_backend: keryx`
- Vendored Keryx Python SDK under `src/keryx/`
- Transport-selection diagnostics and Keryx-aware node and pool paths
- Hermes Fabric generated-catalog, type, test, and build gates in root CI
- Clean-wheel installation and packaged-resource smoke checks in CI and release workflows

### Changed

- Public product and contributor documentation now describes Keryx as primary transport and AgentAnycast as legacy/fallback only
- Hermes Fabric profile resolution honors `HERMES_PROFILES_DIR`, then `HERMES_HOME/profiles`, before the default home
- Linux Fabric runtime service ownership detection falls back to `fuser` when `lsof` is unavailable
- CI and release workflows run both the legacy compatibility SDK tests and Hermes Agency/Keryx tests

### Security

- Pool HTTP mutations fail closed when bearer-token authentication is not configured
- Recovered remote tasks revalidate sender trust before execution
- Hermes Fabric rejects profile configuration writes that escape the configured profiles root through symlinks

### Notes

- External Keryx binaries (`keryxd`, `keryx-relay`) and migration or dual-run scripts live in the separate `hermes-keryx` repository
- Historical AgentAnycast Python SDK release notes are preserved in [`src/agentanycast/CHANGELOG.md`](src/agentanycast/CHANGELOG.md)
