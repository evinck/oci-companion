#!/bin/bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  scripts/deploy-remote-podman.sh [options] [-- app-args...]

Build the OCI Companion container image locally, copy it to a remote host,
load it with Podman, replace the existing container, and start the new one.

Defaults target the current remote deployment host:
  SSH target:     opc@92.5.164.246
  Image tag:      oci-companion:remote
  Container name: oci-companion
  Host port:      443

Options:
  --ssh-target <target>       SSH target. Default: opc@92.5.164.246
  --image-tag <tag>           Local and remote image tag. Default: oci-companion:remote
  --container-name <name>     Remote Podman container name. Default: oci-companion
  --remote-dir <path>         Remote runtime directory. Default: $HOME/oci-companion
  --remote-oci-dir <path>     Remote OCI config directory. Default: $HOME/.oci
  --host-port <port>          Host port mapped to container 8080. Default: 443
  --remote-podman <mode>      Remote Podman mode: auto, rootless, or sudo. Default: auto
  --platform <platform>       Build platform. Default: inferred from remote uname -m
  --containerfile <path>      Containerfile relative to repo root. Default: Dockerfile
  --env-file <path>           Env file to copy to remote. Default: .env-oci-companion.osc-cloud.com
  --certs-dir <path>          Certs directory to copy to remote. Default: certs when present
  --data-file <path>          data.json to copy for --ui-debug. Default: DocumentRoot/data.json
  --no-copy-env               Do not copy the local env file
  --no-copy-certs             Do not copy the local certs directory
  --no-selinux-label          Do not append :Z to remote bind mounts
  --stop-timeout <seconds>    Seconds to wait before killing old container. Default: 20
  --keep-remote-artifacts     Keep transferred tar files on the remote host
  --no-cache                  Build without cache
  -h, --help                  Show this help text

Examples:
  scripts/deploy-remote-podman.sh
  scripts/deploy-remote-podman.sh --ssh-target opc@92.5.164.246 -- --noauth
  scripts/deploy-remote-podman.sh -- --ui-debug --noauth
EOF
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"

ssh_target="${SSH_TARGET:-opc@92.5.164.246}"
image_tag="${IMAGE_TAG:-oci-companion:remote}"
container_name="${CONTAINER_NAME:-oci-companion}"
remote_dir="${REMOTE_DIR:-}"
remote_oci_dir="${REMOTE_OCI_DIR:-}"
host_port="${HOST_PORT:-443}"
remote_podman_mode="${REMOTE_PODMAN_MODE:-auto}"
platform="${PLATFORM:-}"
containerfile="Dockerfile"
env_file="${ENV_FILE:-${repo_root}/.env-oci-companion.osc-cloud.com}"
certs_dir="${CERTS_DIR:-${repo_root}/certs}"
data_file="${DATA_FILE:-${repo_root}/DocumentRoot/data.json}"
copy_env=1
copy_certs=1
selinux_suffix=":Z"
stop_timeout="${STOP_TIMEOUT:-20}"
keep_remote_artifacts=0
no_cache=0
app_args=()

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

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ssh-target)
            ssh_target="$2"
            shift 2
            ;;
        --image-tag)
            image_tag="$2"
            shift 2
            ;;
        --container-name)
            container_name="$2"
            shift 2
            ;;
        --remote-dir)
            remote_dir="$2"
            shift 2
            ;;
        --remote-oci-dir)
            remote_oci_dir="$2"
            shift 2
            ;;
        --host-port)
            host_port="$2"
            shift 2
            ;;
        --remote-podman)
            remote_podman_mode="$2"
            shift 2
            ;;
        --platform)
            platform="$2"
            shift 2
            ;;
        --containerfile)
            containerfile="$2"
            shift 2
            ;;
        --env-file)
            env_file="$2"
            shift 2
            ;;
        --certs-dir)
            certs_dir="$2"
            shift 2
            ;;
        --data-file)
            data_file="$2"
            shift 2
            ;;
        --no-copy-env)
            copy_env=0
            shift
            ;;
        --no-copy-certs)
            copy_certs=0
            shift
            ;;
        --no-selinux-label)
            selinux_suffix=""
            shift
            ;;
        --stop-timeout)
            stop_timeout="$2"
            shift 2
            ;;
        --keep-remote-artifacts)
            keep_remote_artifacts=1
            shift
            ;;
        --no-cache)
            no_cache=1
            shift
            ;;
        --)
            shift
            app_args=("$@")
            break
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

containerfile_path="${repo_root}/${containerfile}"
if [[ ! -f "${containerfile_path}" ]]; then
    echo "Containerfile not found: ${containerfile_path}" >&2
    exit 1
fi

if ! command -v podman >/dev/null 2>&1; then
    echo "Podman not found. Install podman before running this deploy script." >&2
    exit 1
fi

if ! [[ "${host_port}" =~ ^[0-9]+$ ]]; then
    echo "--host-port must be a numeric TCP port: ${host_port}" >&2
    exit 1
fi

case "${remote_podman_mode}" in
    auto|rootless|sudo)
        ;;
    *)
        echo "--remote-podman must be one of: auto, rootless, sudo" >&2
        exit 1
        ;;
esac

use_remote_sudo=0
case "${remote_podman_mode}" in
    auto)
        if (( host_port < 1024 )); then
            use_remote_sudo=1
        fi
        ;;
    sudo)
        use_remote_sudo=1
        ;;
    rootless)
        if (( host_port < 1024 )); then
            echo "Warning: rootless Podman usually cannot bind privileged port ${host_port}." >&2
            echo "Use --remote-podman auto or --remote-podman sudo unless the remote host allows unprivileged low ports." >&2
        fi
        ;;
esac

tmp_dir="$(mktemp -d)"
cleanup() {
    rm -rf "${tmp_dir}"
}
trap cleanup EXIT

echo "Resolving remote home on ${ssh_target}..."
remote_home="$(ssh "${ssh_target}" 'printf "%s" "$HOME"')"
if [[ -z "${remote_dir}" ]]; then
    remote_dir="${remote_home}/oci-companion"
fi
if [[ -z "${remote_oci_dir}" ]]; then
    remote_oci_dir="${remote_home}/.oci"
fi

if [[ "${use_remote_sudo}" -eq 1 ]]; then
    echo "Host port ${host_port} is privileged; remote deploy will use sudo podman."
    if ! ssh "${ssh_target}" 'sudo -n true' >/dev/null; then
        echo "Remote passwordless sudo is required to bind port ${host_port} with podman." >&2
        echo "Use --host-port 8443, configure low-port binding on the remote host, or allow sudo for the SSH user." >&2
        exit 1
    fi
fi

if [[ -z "${platform}" ]]; then
    echo "Detecting remote architecture..."
    remote_arch="$(ssh "${ssh_target}" 'uname -m')"
    case "${remote_arch}" in
        aarch64|arm64)
            platform="linux/arm64"
            ;;
        x86_64|amd64)
            platform="linux/amd64"
            ;;
        *)
            echo "Unsupported remote architecture '${remote_arch}'. Pass --platform explicitly." >&2
            exit 1
            ;;
    esac
fi

echo "Preparing remote runtime directory ${remote_dir}..."
ssh "${ssh_target}" bash -s -- "${remote_dir}" <<'REMOTE_PREP'
set -euo pipefail
remote_dir="$1"
mkdir -p "${remote_dir}"
REMOTE_PREP

build_cmd=(podman build --platform "${platform}" -t "${image_tag}" -f "${containerfile_path}")
if [[ "${no_cache}" -eq 1 ]]; then
    build_cmd+=(--no-cache)
fi
build_cmd+=("${repo_root}")

echo "Building ${image_tag} for ${platform} with podman..."
"${build_cmd[@]}"

image_archive="${tmp_dir}/oci-companion-image.tar"
remote_image_archive="${remote_dir}/oci-companion-image.tar"
echo "Saving image archive..."
podman save -o "${image_archive}" "${image_tag}"

echo "Copying image archive to ${ssh_target}:${remote_image_archive}..."
scp "${image_archive}" "${ssh_target}:${remote_image_archive}"

if [[ "${copy_env}" -eq 1 ]]; then
    if [[ -f "${env_file}" ]]; then
        echo "Copying env file to ${ssh_target}:${remote_dir}/.env..."
        scp "${env_file}" "${ssh_target}:${remote_dir}/.env"
        ssh "${ssh_target}" chmod 600 "${remote_dir}/.env"
    else
        echo "Env file not found at ${env_file}; remote container will use existing env file if present."
    fi
fi

remote_certs_archive="${remote_dir}/certs.tar.gz"
if [[ "${copy_certs}" -eq 1 ]]; then
    if [[ -d "${certs_dir}" ]]; then
        certs_archive="${tmp_dir}/certs.tar.gz"
        echo "Packing certs from ${certs_dir}..."
        tar -czf "${certs_archive}" -C "${certs_dir}" .
        echo "Copying certs archive to ${ssh_target}:${remote_certs_archive}..."
        scp "${certs_archive}" "${ssh_target}:${remote_certs_archive}"
    else
        echo "Certs directory not found at ${certs_dir}; remote container will use existing certs if present."
    fi
fi

use_existing_data=0
if has_arg "--ui-debug" "${app_args[@]}" || has_arg "--keep-existing-data" "${app_args[@]}"; then
    use_existing_data=1
fi

remote_data_file="${remote_dir}/data.json"
if [[ "${use_existing_data}" -eq 1 ]]; then
    if [[ ! -f "${data_file}" ]]; then
        echo "UI debug mode requires a data file, but it was not found: ${data_file}" >&2
        exit 1
    fi
    echo "Copying data file to ${ssh_target}:${remote_data_file}..."
    scp "${data_file}" "${ssh_target}:${remote_data_file}"
fi

echo "Loading image and replacing remote container..."
ssh "${ssh_target}" bash -s -- \
    "${remote_dir}" \
    "${remote_image_archive}" \
    "${remote_certs_archive}" \
    "${remote_data_file}" \
    "${use_existing_data}" \
    "${image_tag}" \
    "${container_name}" \
    "${host_port}" \
    "${remote_oci_dir}" \
    "${selinux_suffix}" \
    "${stop_timeout}" \
    "${keep_remote_artifacts}" \
    "${use_remote_sudo}" \
    "${app_args[@]}" <<'REMOTE_DEPLOY'
set -euo pipefail

remote_dir="$1"
remote_image_archive="$2"
remote_certs_archive="$3"
remote_data_file="$4"
use_existing_data="$5"
image_tag="$6"
container_name="$7"
host_port="$8"
remote_oci_dir="$9"
selinux_suffix="${10}"
stop_timeout="${11}"
keep_remote_artifacts="${12}"
use_remote_sudo="${13}"
shift 13
app_args=("$@")

podman_cmd=(podman)
if [[ "${use_remote_sudo}" -eq 1 ]]; then
    podman_cmd=(sudo -n podman)
fi

if [[ -f "${remote_certs_archive}" ]]; then
    mkdir -p "${remote_dir}/certs"
    tar -xzf "${remote_certs_archive}" -C "${remote_dir}/certs"
    chmod 600 "${remote_dir}"/certs/*key*.pem 2>/dev/null || true
fi

"${podman_cmd[@]}" load -i "${remote_image_archive}"

if [[ "${use_remote_sudo}" -eq 1 ]] && podman container exists "${container_name}" >/dev/null 2>&1; then
    echo "Stopping existing rootless container ${container_name}..."
    podman stop --time "${stop_timeout}" "${container_name}" >/dev/null 2>&1 || \
        podman kill "${container_name}" >/dev/null 2>&1 || true
    podman rm -f "${container_name}" >/dev/null 2>&1 || true
fi

if "${podman_cmd[@]}" container exists "${container_name}" >/dev/null 2>&1; then
    echo "Stopping existing container ${container_name}..."
    "${podman_cmd[@]}" stop --time "${stop_timeout}" "${container_name}" >/dev/null 2>&1 || \
        "${podman_cmd[@]}" kill "${container_name}" >/dev/null 2>&1 || true
    "${podman_cmd[@]}" rm -f "${container_name}" >/dev/null 2>&1 || true
fi

run_args=(
    -d
    --name "${container_name}"
    --restart unless-stopped
    -p "${host_port}:8080"
)

if [[ -d "${remote_oci_dir}" ]]; then
    run_args+=(-v "${remote_oci_dir}:/root/.oci${selinux_suffix}")
else
    echo "Warning: remote OCI directory not found: ${remote_oci_dir}" >&2
fi

if [[ -d "${remote_dir}/certs" ]]; then
    run_args+=(-v "${remote_dir}/certs:/app/certs${selinux_suffix}")
else
    echo "Warning: remote certs directory not found: ${remote_dir}/certs" >&2
fi

if [[ -f "${remote_dir}/.env" ]]; then
    run_args+=(-v "${remote_dir}/.env:/app/.env${selinux_suffix}")
else
    echo "Warning: remote env file not found: ${remote_dir}/.env" >&2
fi

if [[ "${use_existing_data}" -eq 1 ]]; then
    if [[ ! -f "${remote_data_file}" ]]; then
        echo "Remote data file not found: ${remote_data_file}" >&2
        exit 1
    fi
    data_mount="${remote_data_file}:/app/DocumentRoot/data.json"
    if [[ -n "${selinux_suffix}" ]]; then
        data_mount+="${selinux_suffix},ro"
    else
        data_mount+=":ro"
    fi
    run_args+=(-v "${data_mount}")
fi

"${podman_cmd[@]}" run "${run_args[@]}" "${image_tag}" "${app_args[@]}"

if [[ "${keep_remote_artifacts}" -eq 0 ]]; then
    rm -f "${remote_image_archive}" "${remote_certs_archive}"
fi

echo "Remote container status:"
"${podman_cmd[@]}" ps --filter "name=^${container_name}$" --format "{{.ID}} {{.Image}} {{.Ports}} {{.Status}} {{.Names}}"
REMOTE_DEPLOY

deploy_url="https://92.5.164.246"
if [[ "${host_port}" != "443" ]]; then
    deploy_url="${deploy_url}:${host_port}"
fi
echo "Deployment complete. Open ${deploy_url}/"
