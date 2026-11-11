# Maintainer: Jasur Sadikov <https://github.com/jasursadikov>
# Prebuilt dependency wheels are intentionally private to this extension.
pkgname=nautilus-git-branch-bin
pkgver=1.0.0
pkgrel=1
pkgdesc='Dim Git branch and tag badges beside Nautilus repository folders'
arch=('x86_64' 'aarch64')
url='https://github.com/jasursadikov/nautilus-git-branch'
license=('MIT' 'MIT-0' 'BSD-3-Clause' 'Apache-2.0' 'LicenseRef-GPL-2.0-only-with-linking-exception')
depends=('nautilus>=51' 'nautilus-python>=4.2' 'python>=3.14' 'python<3.15' 'python-gobject' 'glibc' 'zlib')
makedepends=('python-pip')
optdepends=('ttf-nerd-fonts-symbols: branch, tag and commit icons')
provides=("nautilus-git-branch=$pkgver")
conflicts=('nautilus-git-branch' 'nautilus-git-branch-git')
options=('!strip' '!debug')
install=nautilus-git-branch.install

_upstream="https://raw.githubusercontent.com/jasursadikov/nautilus-git-branch/v$pkgver"
source=(
    "nautilus-git-branch-$pkgver.py::$_upstream/nautilus_git_branch.py"
    "nautilus-git-branch-$pkgver-README.md::$_upstream/README.md"
    "nautilus-git-branch-$pkgver-LICENSE::$_upstream/LICENSE"
    'https://files.pythonhosted.org/packages/b6/ae/315bbeee126a769cbde43cf4908acb4b40408d8bf8bbf334dd7368d8dadf/pycparser-3.12-py3-none-any.whl'
)
source_x86_64=(
    'https://files.pythonhosted.org/packages/b6/01/f6e3c18ad9dabeb7302575b1174864fd90842bd4afedb3f5bdd926047ff4/pygit2-1.20.1-cp314-cp314-manylinux_2_26_x86_64.manylinux_2_28_x86_64.whl'
    'https://files.pythonhosted.org/packages/e9/02/4e7d553a7ac4b4238b38b3c1b80d486e9d4436f8d2acbf87a0997fe3f402/cffi-2.1.1-cp314-cp314-manylinux2014_x86_64.manylinux_2_17_x86_64.whl'
)
source_aarch64=(
    'https://files.pythonhosted.org/packages/8f/96/99c223eebe0d8ad5310648deea8a7fe5dbbcd0aa1111ee412cfc8accd028/pygit2-1.20.1-cp314-cp314-manylinux_2_26_aarch64.manylinux_2_28_aarch64.whl'
    'https://files.pythonhosted.org/packages/67/b8/b42132ca113dc567d37684437b46ca1dafc885902b02a110a02d5b511857/cffi-2.1.1-cp314-cp314-manylinux2014_aarch64.manylinux_2_17_aarch64.whl'
)
noextract=(
    'pycparser-3.12-py3-none-any.whl'
    "${source_x86_64[@]##*/}"
    "${source_aarch64[@]##*/}"
)
sha256sums=(
    '6482dd501ce99e15c3dac06d7e22904d82b5e6f9e35c7f3d1375ecadc7efe1cd'
    '2ed9707099405f9d7cbbbbeb81afab4e1dc9420be998854d119d0b1cb43c9e2f'
    'b11a0f75f04e23df3aa63146b783a01a7b9b74345bcb758285bc3b1043f8cad0'
    'a076f3f489b39b43ed13563a1dafe42447445bec2e294154ec5c57fcdda4c85e'
)
sha256sums_x86_64=(
    '860c971fd53a9f14713a51b6343827b82d2b7dc7955e8c28c81ca3c90033b6a2'
    'b0431303acaea1089ad4b3e9ce4e6518193def1118d4073ca848635ee4ea2e96'
)
sha256sums_aarch64=(
    '3d507bf62f5d447e382667411972921e0afe923e9567f3476a1f7b73db8bf49b'
    '58acb8ab8e295e6c5ea12f888cbb13cf21511ef2a3303a23f4325c29d17fe5c1'
)

prepare() {
    cp "$srcdir/nautilus-git-branch-$pkgver.py" "$srcdir/nautilus_git_branch.py"
    cp "$srcdir/nautilus-git-branch-$pkgver-README.md" "$srcdir/README.md"
    cp "$srcdir/nautilus-git-branch-$pkgver-LICENSE" "$srcdir/LICENSE"
}

build() {
    python -c 'import sys; assert sys.version_info[:2] == (3, 14), "Rebuild the wheel sources for this Python ABI"'
    rm -rf -- "$srcdir/vendor"
    python -m pip install --no-index --no-deps --no-compile --no-cache-dir \
        --disable-pip-version-check --no-warn-script-location --ignore-installed \
        --only-binary=:all: --target "$srcdir/vendor" "$srcdir/"*.whl
}

check() {
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$srcdir/vendor:$srcdir" python -c \
        'import pygit2; import nautilus_git_branch; assert pygit2.__version__ == "1.20.1"'
}

package() {
    local extension_dir="$pkgdir/usr/share/nautilus-python/extensions"
    local vendor_dir="$pkgdir/usr/lib/nautilus-git-branch/python3.14"
    local license_dir="$pkgdir/usr/share/licenses/$pkgname"
    install -Dm644 "$srcdir/nautilus_git_branch.py" "$extension_dir/nautilus_git_branch.py"
    install -d "$vendor_dir"
    cp -r --preserve=mode,timestamps "$srcdir/vendor/." "$vendor_dir/"
    # Local wheel provenance contains the build directory, not an upstream URL.
    rm -f "$vendor_dir/"*.dist-info/direct_url.json
    install -Dm644 "$srcdir/README.md" "$pkgdir/usr/share/doc/nautilus-git-branch/README.md"
    install -Dm644 "$srcdir/LICENSE" "$license_dir/LICENSE"
    # Keep upstream license texts and metadata with the binaries, and expose
    # the supplied license texts in Arch's normal license directory too.
    local metadata
    for metadata in "$srcdir/vendor/"*.dist-info; do
        if [[ -d "$metadata/licenses" ]]; then
            install -d "$license_dir/${metadata##*/}"
            cp -r --preserve=mode,timestamps "$metadata/licenses/." "$license_dir/${metadata##*/}/"
        fi
    done
}
