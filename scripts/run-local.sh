#!/bin/bash

# To run in UI debug mode:
# scripts/run-local.sh --ui-debug
#
# To run without OCI IAM authentication:
# scripts/run-local.sh --noauth

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-oci-companion:local}"
LOCAL_ENV_FILE="${LOCAL_ENV_FILE:-${REPO_ROOT}/.env-localhost}"
DATA_FILE="${DATA_FILE:-${REPO_ROOT}/DocumentRoot/data.json}"

is_truthy() {
    case "${1:-}" in
        1|true|TRUE|yes|YES|on|ON)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

has_arg() {
    local expected="$1"
    shift
    local arg
    for arg in "$@"; do
        if [[ "${arg}" == "${expected}" ]]; then
            return 0
        fi
    done
    return 1
}

env_file_value() {
    local key="$1"
    local line

    if [[ ! -f "${LOCAL_ENV_FILE}" ]]; then
        return 1
    fi

    line="$(grep -E "^[[:space:]]*${key}=" "${LOCAL_ENV_FILE}" | tail -n 1 || true)"
    if [[ -z "${line}" ]]; then
        return 1
    fi

    line="${line#*=}"
    line="${line%\"}"
    line="${line#\"}"
    line="${line%\'}"
    line="${line#\'}"
    printf '%s' "${line}"
}

ui_debug_value="${UI_DEBUG:-${OCI_COMPANION_UI_DEBUG:-}}"
if [[ -z "${ui_debug_value}" ]]; then
    ui_debug_value="$(env_file_value OCI_COMPANION_UI_DEBUG || true)"
fi
if [[ -z "${ui_debug_value}" ]]; then
    ui_debug_value="$(env_file_value UI_DEBUG || true)"
fi

noauth_value="${NOAUTH:-${OCI_COMPANION_NOAUTH:-}}"
if [[ -z "${noauth_value}" ]]; then
    noauth_value="$(env_file_value OCI_COMPANION_NOAUTH || true)"
fi
if [[ -z "${noauth_value}" ]]; then
    noauth_value="$(env_file_value NOAUTH || true)"
fi

use_existing_data=0
if is_truthy "${ui_debug_value}" || has_arg "--ui-debug" "$@" || has_arg "--keep-existing-data" "$@"; then
    use_existing_data=1
fi

container_args=("$@")
if is_truthy "${ui_debug_value}" && ! has_arg "--ui-debug" "$@" && ! has_arg "--keep-existing-data" "$@"; then
    container_args+=("--ui-debug")
fi

if is_truthy "${noauth_value}" && ! has_arg "--noauth" "$@"; then
    container_args+=("--noauth")
fi

podman build -t "${IMAGE_NAME}" -f "${REPO_ROOT}/Dockerfile" "${REPO_ROOT}"

run_args=(
    --rm
    -it
    -p 8080:8080
    -v "${HOME}/.oci:/root/.oci:Z"
)

if [[ -d "${REPO_ROOT}/certs" ]]; then
    run_args+=(-v "${REPO_ROOT}/certs:/app/certs:Z")
fi

if [[ -f "${LOCAL_ENV_FILE}" ]]; then
    run_args+=(-v "${LOCAL_ENV_FILE}:/app/.env:Z")
fi

if has_arg "--noauth" "${container_args[@]}"; then
    run_args+=(-e OCI_COMPANION_NOAUTH=true)
fi

if [[ "${use_existing_data}" -eq 1 ]]; then
    if [[ ! -f "${DATA_FILE}" ]]; then
        echo "UI debug mode requires ${DATA_FILE}" >&2
        exit 1
    fi
    run_args+=(-v "${DATA_FILE}:/app/DocumentRoot/data.json:Z,ro")
fi

podman run "${run_args[@]}" "${IMAGE_NAME}" "${container_args[@]}"
