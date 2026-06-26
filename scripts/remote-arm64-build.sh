#!/bin/bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  scripts/remote-arm64-build.sh <ssh-target> <image-tag> [options]

Example:
  scripts/remote-arm64-build.sh opc@arm-builder docker.io/yourrepo/oci-companion:arm64 --push

Options:
  --remote-dir <path>       Remote working directory. Default: /tmp/oci-companion-arm64-build-<timestamp>
  --platform <platform>     Build platform. Default: linux/arm64
  --containerfile <path>    Containerfile path relative to repo root. Default: Dockerfile
  --push                    Push the built image from the remote host
  --keep-remote-dir         Leave the remote working directory in place after the build
  -h, --help                Show this help text
EOF
}

if [[ $# -eq 1 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
    usage
    exit 0
fi

if [[ $# -lt 2 ]]; then
    usage
    exit 1
fi

SSH_TARGET="$1"
IMAGE_TAG="$2"
shift 2

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PLATFORM="linux/arm64"
CONTAINERFILE="Dockerfile"
REMOTE_DIR="/tmp/oci-companion-arm64-build-$(date +%Y%m%d%H%M%S)"
PUSH_IMAGE=0
KEEP_REMOTE_DIR=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --remote-dir)
            REMOTE_DIR="$2"
            shift 2
            ;;
        --platform)
            PLATFORM="$2"
            shift 2
            ;;
        --containerfile)
            CONTAINERFILE="$2"
            shift 2
            ;;
        --push)
            PUSH_IMAGE=1
            shift
            ;;
        --keep-remote-dir)
            KEEP_REMOTE_DIR=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 1
            ;;
    esac
done

if [[ ! -f "${REPO_ROOT}/${CONTAINERFILE}" ]]; then
    echo "Containerfile not found: ${CONTAINERFILE}" >&2
    exit 1
fi

echo "Checking remote architecture on ${SSH_TARGET}..."
REMOTE_ARCH="$(ssh "$SSH_TARGET" "uname -m")"
if [[ "${REMOTE_ARCH}" != "aarch64" && "${REMOTE_ARCH}" != "arm64" ]]; then
    echo "Remote host reports '${REMOTE_ARCH}', not an ARM64 architecture." >&2
    exit 1
fi

echo "Syncing build context to ${SSH_TARGET}:${REMOTE_DIR}..."
tar \
    --exclude-vcs \
    --exclude='./.codex' \
    --exclude='./__pycache__' \
    --exclude='./DocumentRoot/data.json' \
    --exclude='./DocumentRoot/data.json.prev' \
    --exclude='./debug' \
    --exclude='./database.debug' \
    -czf - \
    -C "$REPO_ROOT" \
    . | ssh "$SSH_TARGET" "rm -rf '$REMOTE_DIR' && mkdir -p '$REMOTE_DIR' && tar -xzf - -C '$REMOTE_DIR'"

REMOTE_BUILD_CMD="cd '$REMOTE_DIR' && podman build --platform '$PLATFORM' -t '$IMAGE_TAG' -f '$CONTAINERFILE' ."
if [[ "$PUSH_IMAGE" -eq 1 ]]; then
    REMOTE_BUILD_CMD+=" && podman push '$IMAGE_TAG'"
fi
if [[ "$KEEP_REMOTE_DIR" -eq 0 ]]; then
    REMOTE_BUILD_CMD+=" && rm -rf '$REMOTE_DIR'"
fi

echo "Running remote Podman build..."
ssh "$SSH_TARGET" "$REMOTE_BUILD_CMD"

echo "Remote build completed for ${IMAGE_TAG}"
