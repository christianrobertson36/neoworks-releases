# Publishing app downloads

Only verified binaries and their release metadata belong here. Private app source stays in the private repository.

Stage an approved package under incoming/{unique-release-name}/package.zip and release.json. Metadata uses appId, version (three-component semver), runtime (native or dotnet), channel (stable or preview), size (exact ZIP byte count), sha256 (lowercase SHA-256), and releaseNotes. Package ZIPs put the executable at the root. Managed packages include the matching DLL, runtimeconfig and dependencies.

The publishing workflow uploads the package as a GitHub Release asset, downloads it again to verify its checksum, then updates the selected app's catalogue entry. A failed publication never advertises unavailable bytes. The launcher is a separate release and never becomes an app catalogue entry.

The incoming folder provides bootstrap uploads for packages below GitHub's individual Git blob limit. Larger packages require direct Release asset uploads and verified catalogue updates.

Stable catalogue: https://raw.githubusercontent.com/christianrobertson36/neoworks-releases/main/catalogue/stable.json

Preview catalogue: https://raw.githubusercontent.com/christianrobertson36/neoworks-releases/main/catalogue/preview.json
