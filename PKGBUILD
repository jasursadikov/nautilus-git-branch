# Maintainer: Jasur Sadikov <https://github.com/jasursadikov>
pkgname=nautilus-git-branch
pkgver=1.0.0
pkgrel=1
pkgdesc='Dim Git branch and tag badges beside Nautilus repository folders'
arch=('any')
url='https://github.com/jasursadikov/nautilus-git-branch'
license=('MIT')
depends=('nautilus' 'nautilus-python' 'python-pygit2')
optdepends=('ttf-nerd-fonts-symbols: branch, tag and commit icons')
install=nautilus-git-branch.install

_upstream="https://raw.githubusercontent.com/jasursadikov/nautilus-git-branch/v$pkgver"
source=(
    "$pkgname-$pkgver.py::$_upstream/src/nautilus-git-branch/nautilus_git_branch.py"
    "$pkgname-$pkgver-README.md::$_upstream/README.md"
    "$pkgname-$pkgver-LICENSE::$_upstream/LICENSE"
)
sha256sums=(
    'b093d614657b66a28b7f86075b67560a440be1d7f3cf083cdb541753381545a1'
    '94d5268da98d54931e906936fcdb6a18ffc955eff1c9924d705691464e9a1e14'
    'b11a0f75f04e23df3aa63146b783a01a7b9b74345bcb758285bc3b1043f8cad0'
)

package() {
    install -Dm644 "$srcdir/$pkgname-$pkgver.py" \
        "$pkgdir/usr/share/nautilus-python/extensions/nautilus_git_branch.py"
    install -Dm644 "$srcdir/$pkgname-$pkgver-README.md" \
        "$pkgdir/usr/share/doc/$pkgname/README.md"
    install -Dm644 "$srcdir/$pkgname-$pkgver-LICENSE" \
        "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
