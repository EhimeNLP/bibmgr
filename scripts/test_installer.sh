#!/bin/sh

set -eu

fail() {
  printf 'installer test: %s\n' "$1" >&2
  exit 1
}

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{ print $1 }'
  else
    shasum -a 256 "$1" | awk '{ print $1 }'
  fi
}

test_root=$(mktemp -d 2>/dev/null || mktemp -d -t bibmgr-installer-test) \
  || fail "could not create a temporary directory"
trap 'rm -rf "$test_root"' 0
trap 'exit 1' 1 2 15

target=x86_64-unknown-linux-musl
version=v9.8.7
asset=bibmgr-$target.tar.gz
fixture_directory=$test_root/fixture
release_directory=$test_root/releases/download/$version
latest_directory=$test_root/releases/latest/download
install_directory=$test_root/bin

mkdir -p "$fixture_directory" "$release_directory" "$latest_directory"
printf '%s\n' '#!/bin/sh' "printf '%s\\n' 'bibmgr 9.8.7'" \
  >"$fixture_directory/bibmgr"
chmod 755 "$fixture_directory/bibmgr"
tar -czf "$release_directory/$asset" -C "$fixture_directory" bibmgr
checksum=$(sha256 "$release_directory/$asset")
printf '%s  %s\n' "$checksum" "$asset" >"$release_directory/$asset.sha256"
cp "$release_directory/$asset" "$latest_directory/$asset"
cp "$release_directory/$asset.sha256" "$latest_directory/$asset.sha256"

BIBMGR_ALLOW_FILE_URL=1 \
BIBMGR_INSTALL_DIR=$install_directory \
BIBMGR_RELEASES_URL=file://$test_root/releases \
BIBMGR_TARGET=$target \
BIBMGR_VERSION=9.8.7 \
  sh scripts/install.sh >"$test_root/version-install.out" 2>&1

[ "$("$install_directory/bibmgr" --version)" = "bibmgr 9.8.7" ] \
  || fail "the requested release was not installed"

rm "$install_directory/bibmgr"
BIBMGR_ALLOW_FILE_URL=1 \
BIBMGR_INSTALL_DIR=$install_directory \
BIBMGR_RELEASES_URL=file://$test_root/releases \
BIBMGR_TARGET=$target \
  sh scripts/install.sh >"$test_root/latest-install.out" 2>&1

[ "$("$install_directory/bibmgr" --version)" = "bibmgr 9.8.7" ] \
  || fail "the latest release was not installed"

printf '%064d  %s\n' 0 "$asset" >"$release_directory/$asset.sha256"
checksum_failure_directory=$test_root/checksum-failure
if BIBMGR_ALLOW_FILE_URL=1 \
  BIBMGR_INSTALL_DIR=$checksum_failure_directory \
  BIBMGR_RELEASES_URL=file://$test_root/releases \
  BIBMGR_TARGET=$target \
  BIBMGR_VERSION=$version \
  sh scripts/install.sh >"$test_root/checksum-failure.out" 2>&1; then
  fail "an invalid checksum was accepted"
fi

grep -q 'checksum verification failed' "$test_root/checksum-failure.out" \
  || fail "checksum failure was not reported"
[ ! -e "$checksum_failure_directory/bibmgr" ] \
  || fail "a binary was installed after checksum verification failed"

printf 'installer tests passed\n'
