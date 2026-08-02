#!/bin/sh

set -eu

repository=${BIBMGR_REPOSITORY:-EhimeNLP/bibmgr}
version=${BIBMGR_VERSION:-latest}
releases_url=${BIBMGR_RELEASES_URL:-https://github.com/$repository/releases}
target=${BIBMGR_TARGET:-}

fail() {
  printf 'bibmgr installer: %s\n' "$1" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

detect_target() {
  system=$(uname -s)
  machine=$(uname -m)

  case "$system" in
    Darwin)
      platform=apple-darwin
      ;;
    Linux)
      platform=unknown-linux-musl
      ;;
    MINGW* | MSYS* | CYGWIN*)
      fail "Windows is not supported by this shell installer; download the Windows ZIP from the GitHub release."
      ;;
    *)
      fail "unsupported operating system: $system"
      ;;
  esac

  case "$machine" in
    x86_64 | amd64)
      architecture=x86_64
      ;;
    arm64 | aarch64)
      architecture=aarch64
      ;;
    *)
      fail "unsupported CPU architecture: $machine"
      ;;
  esac

  printf '%s-%s\n' "$architecture" "$platform"
}

download() {
  source_url=$1
  destination=$2

  case "$source_url" in
    https://*)
      curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
        --output "$destination" "$source_url"
      ;;
    file://*)
      if [ "${BIBMGR_ALLOW_FILE_URL:-0}" != 1 ]; then
        fail "file URLs are reserved for installer tests"
      fi
      curl --proto '=file' --fail --location --silent --show-error \
        --output "$destination" "$source_url"
      ;;
    *)
      fail "release URL must use HTTPS"
      ;;
  esac
}

sha256() {
  if command_exists sha256sum; then
    sha256sum "$1" | awk '{ print $1 }'
  elif command_exists shasum; then
    shasum -a 256 "$1" | awk '{ print $1 }'
  else
    fail "SHA-256 verification requires sha256sum or shasum"
  fi
}

command_exists curl || fail "curl is required"
command_exists tar || fail "tar is required"

if [ -z "$target" ]; then
  target=$(detect_target)
fi

case "$target" in
  x86_64-unknown-linux-musl | aarch64-unknown-linux-musl | \
    x86_64-apple-darwin | aarch64-apple-darwin)
    ;;
  *)
    fail "unsupported installation target: $target"
    ;;
esac

if [ "$version" = latest ]; then
  release_path=latest/download
else
  case "$version" in
    v*)
      ;;
    *)
      version=v$version
      ;;
  esac
  case "$version" in
    v[0-9]*)
      ;;
    *)
      fail "BIBMGR_VERSION must be 'latest' or a v-prefixed release version"
      ;;
  esac
  case "${version#v}" in
    *[!0-9A-Za-z.+-]*)
      fail "BIBMGR_VERSION contains unsupported characters"
      ;;
  esac
  release_path=download/$version
fi

if [ -n "${BIBMGR_INSTALL_DIR:-}" ]; then
  install_dir=$BIBMGR_INSTALL_DIR
elif [ -n "${XDG_BIN_HOME:-}" ]; then
  install_dir=$XDG_BIN_HOME
elif [ -n "${HOME:-}" ]; then
  install_dir=$HOME/.local/bin
else
  fail "HOME is unset; set BIBMGR_INSTALL_DIR explicitly"
fi

archive=bibmgr-$target.tar.gz
archive_url=$releases_url/$release_path/$archive
checksum_url=$archive_url.sha256

temporary_directory=$(mktemp -d 2>/dev/null || mktemp -d -t bibmgr-installer) \
  || fail "could not create a temporary directory"
installed_temporary=

cleanup() {
  rm -rf "$temporary_directory"
  if [ -n "$installed_temporary" ]; then
    rm -f "$installed_temporary"
  fi
}
trap cleanup 0
trap 'exit 1' 1 2 15

archive_path=$temporary_directory/$archive
checksum_path=$archive_path.sha256
extract_directory=$temporary_directory/extracted

printf 'Downloading bibmgr for %s...\n' "$target"
download "$archive_url" "$archive_path"
download "$checksum_url" "$checksum_path"

expected_checksum=$(awk 'NR == 1 { print $1 }' "$checksum_path")
[ "${#expected_checksum}" -eq 64 ] \
  || fail "release checksum is not a SHA-256 digest"
case "$expected_checksum" in
  *[!0-9A-Fa-f]*)
    fail "release checksum is not a SHA-256 digest"
    ;;
esac
expected_checksum=$(printf '%s' "$expected_checksum" | tr '[:upper:]' '[:lower:]')
actual_checksum=$(sha256 "$archive_path")
[ "$actual_checksum" = "$expected_checksum" ] \
  || fail "checksum verification failed for $archive"

mkdir -p "$extract_directory"
tar -xzf "$archive_path" -C "$extract_directory"
[ -f "$extract_directory/bibmgr" ] \
  || fail "release archive does not contain the bibmgr executable"

mkdir -p "$install_dir"
installed_temporary=$install_dir/.bibmgr-install-$$
cp "$extract_directory/bibmgr" "$installed_temporary"
chmod 755 "$installed_temporary"
mv "$installed_temporary" "$install_dir/bibmgr"
installed_temporary=

"$install_dir/bibmgr" --version
printf 'Installed bibmgr to %s\n' "$install_dir/bibmgr"

case ":${PATH:-}:" in
  *":$install_dir:"*)
    ;;
  *)
    printf 'Add %s to PATH to run bibmgr from any directory.\n' "$install_dir" >&2
    ;;
esac
