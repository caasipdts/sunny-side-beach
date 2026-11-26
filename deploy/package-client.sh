#!/usr/bin/env bash
# Packager script to create a lightweight USB bundle for the client machine
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE_DIR="${REPO_ROOT}/dist/sunnyside-client-bundle"
OUTPUT_ZIP="${REPO_ROOT}/sunnyside-client-bundle.zip"

echo "==================================================="
echo " Packaging Sunnyside Beach Client Bundle"
echo "==================================================="

rm -rf "${BUNDLE_DIR}" "${OUTPUT_ZIP}"
mkdir -p "${BUNDLE_DIR}/custom-addons"
mkdir -p "${BUNDLE_DIR}/deploy/client"

echo "Copying custom modules..."
cp -R "${REPO_ROOT}/custom-addons/sunnyside_visitor_management" "${BUNDLE_DIR}/custom-addons/"
cp -R "${REPO_ROOT}/custom-addons/sunnyside_sync" "${BUNDLE_DIR}/custom-addons/"

# Clean any pycache or temporary files
find "${BUNDLE_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "${BUNDLE_DIR}" -type f -name "*.pyc" -delete 2>/dev/null || true

echo "Copying client deployment files..."
cp "${REPO_ROOT}/deploy/client/compose.yaml" "${BUNDLE_DIR}/deploy/client/"
cp "${REPO_ROOT}/deploy/client/env.example" "${BUNDLE_DIR}/deploy/client/"
cp "${REPO_ROOT}/deploy/client/setup-client.ps1" "${BUNDLE_DIR}/deploy/client/"
cp "${REPO_ROOT}/deploy/client/setup-client.sh" "${BUNDLE_DIR}/deploy/client/"

# Make shell scripts executable
chmod +x "${BUNDLE_DIR}/deploy/client/setup-client.sh"

cat <<'EOF' > "${BUNDLE_DIR}/README.txt"
======================================================
 SUNNYSIDE BEACH - RECEPTION OFFLINE INSTALLATION
======================================================

PREREQUISITE:
1. Make sure Docker Desktop is installed and running on this machine.
   (Download free from: https://www.docker.com/products/docker-desktop)

INSTALLATION:
- On Windows:
  1. Open PowerShell inside this folder.
  2. Run: .\deploy\client\setup-client.ps1
  3. A shortcut "Sunnyside Beach Reception" will appear on the Desktop!

- On Linux / Mac:
  1. Open Terminal inside this folder.
  2. Run: bash deploy/client/setup-client.sh

AFTER SETUP:
Send the generated file "deploy/client/cloud-pairing.json" to the Azure Cloud Administrator.
EOF

echo "Creating ZIP archive..."
cd "${BUNDLE_DIR}/.."
zip -r "${OUTPUT_ZIP}" "sunnyside-client-bundle" >/dev/null

echo "==================================================="
echo " SUCCESS: Client bundle created at:"
echo " ${OUTPUT_ZIP}"
echo " Size: $(du -sh "${OUTPUT_ZIP}" | awk '{print $1}')"
echo "==================================================="
echo "You can now copy '${OUTPUT_ZIP}' directly onto your USB flash drive!"
