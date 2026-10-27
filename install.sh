#!/usr/bin/env sh
# gitex'i kurar: uv, Python 3.12 ve `gitex` komutu. Sonunda kurulum sihirbazını açar.
#
# Repo klonlandıktan sonra tek komut:   ./install.sh
#   --no-setup         Kurulumdan sonra `gitex setup` sihirbazını başlatma
#   --no-modify-path   Kabuk PATH ayarına dokunma (CI ve test için)
#   --uninstall        gitex'i kaldır
#
# - uv yoksa resmi kurucusuyla kurulur (https://docs.astral.sh/uv/)
# - Python 3.12'yi uv indirir; sistemdeki Python'a dokunulmaz
# - Tekrar çalıştırmak güvenlidir; güncelleme için de aynı komut kullanılır.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# Bu betiği başlatan kabuğun PATH'i (sonda uyarmak için).
CALLER_PATH=$PATH
SETUP=1
MODIFY_PATH=1
UNINSTALL=0

for arg in "$@"; do
    case "$arg" in
        --no-setup) SETUP=0 ;;
        --no-modify-path) MODIFY_PATH=0 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) printf 'Bilinmeyen seçenek: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

if [ -t 1 ]; then C='\033[36m'; G='\033[32m'; R='\033[31m'; D='\033[2m'; N='\033[0m'; else C=; G=; R=; D=; N=; fi
step() { printf "${C}==> %s${N}\n" "$1"; }
ok() { printf "${G}    %s${N}\n" "$1"; }
fail() { printf "${R}Hata: %s${N}\n" "$1" >&2; [ -n "${2:-}" ] && printf "${D}İpucu: %s${N}\n" "$2" >&2; exit 1; }

find_uv() {
    if command -v uv >/dev/null 2>&1; then command -v uv; return; fi
    for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -x "$candidate" ]; then echo "$candidate"; return; fi
    done
}

UV=$(find_uv || true)

if [ "$UNINSTALL" = 1 ]; then
    [ -n "$UV" ] || fail "uv bulunamadı; gitex zaten kurulu görünmüyor."
    step "gitex kaldırılıyor"
    "$UV" tool uninstall gitex
    ok "Kaldırıldı. Anahtar kasasındaki kayıtlar için önce: gitex auth logout"
    exit 0
fi

step "git kontrol ediliyor"
command -v git >/dev/null 2>&1 || fail "git bulunamadı." "Kurun: https://git-scm.com/downloads"
ok "$(git --version)"

if [ -z "$UV" ]; then
    step "uv kuruluyor (Python ve paket yöneticisi, astral.sh)"
    [ "$MODIFY_PATH" = 1 ] || export UV_NO_MODIFY_PATH=1
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh || fail "uv indirilemedi." "İnternet bağlantısını kontrol edin: https://docs.astral.sh/uv/"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh || fail "uv indirilemedi." "İnternet bağlantısını kontrol edin: https://docs.astral.sh/uv/"
    else
        fail "uv'yi indirmek için curl ya da wget gerekli."
    fi
    UV=$(find_uv || true)
    [ -n "$UV" ] || fail "uv kuruldu ama bulunamadı." "Yeni bir terminal açıp bu betiği tekrar çalıştırın."
fi
ok "uv: $("$UV" --version)"

step "Python 3.12 ve gitex kuruluyor (ilk seferde birkaç dakika sürebilir)"
"$UV" tool install --force --python 3.12 "$ROOT" || fail "gitex kurulamadı." "Yukarıdaki hatayı kontrol edin; bu betiği tekrar çalıştırmak güvenlidir."

BIN_DIR=$("$UV" tool dir --bin)
if [ "$MODIFY_PATH" = 1 ]; then
    "$UV" tool update-shell >/dev/null 2>&1 || true
fi
PATH="$BIN_DIR:$PATH"
export PATH
[ -x "$BIN_DIR/gitex" ] || fail "gitex komutu bulunamadı: $BIN_DIR/gitex"
ok "$("$BIN_DIR/gitex" --version) kuruldu → $BIN_DIR/gitex"

echo
if [ "$SETUP" = 1 ] && [ -t 0 ]; then
    step "Kurulum sihirbazı başlatılıyor (model, API anahtarı, GitLab)"
    "$BIN_DIR/gitex" setup || true
fi

echo
printf "${G}Kurulum tamam.${N}\n"
echo "  Başlamak için bir git deposunda:  gitex ask \"Son değişiklikler neler?\""
echo "  Ayarlar: gitex setup  ·  Kontrol: gitex doctor  ·  Tüm komutlar: gitex --help"
if [ "$MODIFY_PATH" = 0 ]; then
    echo "  PATH değiştirilmedi; komut: $BIN_DIR/gitex"
else
    # Bir alt süreç, kendisini başlatan kabuğun PATH'ini değiştiremez.
    case ":$CALLER_PATH:" in
        *":$BIN_DIR:"*) ;;
        *)
            echo
            printf "\033[33m  ÖNEMLİ: Bu terminal gitex'i henüz tanımıyor.\033[0m\n"
            printf "\033[33m  Terminali kapatıp yeniden açın — ya da bu pencerede hemen kullanmak için:\033[0m\n"
            echo "    export PATH=\"$BIN_DIR:\$PATH\""
            ;;
    esac
fi
