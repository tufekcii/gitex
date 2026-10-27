#!/usr/bin/env sh
# gitex'i kurar: uv, Python 3.12 ve `gitex` komutu. Sonunda kurulum sihirbazını açar.
# Installs gitex: uv, Python 3.12 and the `gitex` command, then opens the setup wizard.
#
#   ./install.sh [--lang tr|en] [--no-setup] [--no-modify-path] [--uninstall]
#
#   --lang tr|en       Dil (verilmezse sorulur) / language (asked if not given)
#   --no-setup         Sihirbazı başlatma / don't start the setup wizard
#   --no-modify-path   PATH'e dokunma (CI) / don't touch PATH (CI)
#   --uninstall        Kaldır / uninstall
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# Bu betiği başlatan kabuğun PATH'i (sonda uyarmak için).
CALLER_PATH=$PATH
SETUP=1
MODIFY_PATH=1
UNINSTALL=0
GX_LANG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --no-setup) SETUP=0 ;;
        --no-modify-path) MODIFY_PATH=0 ;;
        --uninstall) UNINSTALL=1 ;;
        --lang) shift; GX_LANG="${1:-}" ;;
        --lang=*) GX_LANG="${1#--lang=}" ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) printf 'Bilinmeyen seçenek / Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

case "$GX_LANG" in
    ""|tr|en) ;;
    *) printf 'Geçersiz dil / Invalid language: %s (tr | en)\n' "$GX_LANG" >&2; exit 2 ;;
esac

# ---------------------------------------------------------------------- dil / language

case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
    tr*|TR*) SYSTEM_LANG=tr ;;
    *) SYSTEM_LANG=en ;;
esac
if [ -z "$GX_LANG" ]; then
    GX_LANG=$SYSTEM_LANG
    if [ -t 0 ] && [ "$UNINSTALL" = 0 ]; then
        if [ "$SYSTEM_LANG" = tr ]; then DEFAULT=1; else DEFAULT=2; fi
        printf '\033[36mDil / Language\033[0m\n'
        echo "   1) Türkçe"
        echo "   2) English"
        while :; do
            printf 'Seçim / Choice [%s]: ' "$DEFAULT"
            read -r ANSWER || ANSWER=""
            [ -n "$ANSWER" ] || ANSWER=$DEFAULT
            case "$ANSWER" in
                1) GX_LANG=tr; break ;;
                2) GX_LANG=en; break ;;
                *) echo "1 / 2" ;;
            esac
        done
        echo
    fi
fi

# t "Türkçe" "English"
t() { if [ "$GX_LANG" = tr ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }

if [ -t 1 ]; then C='\033[36m'; G='\033[32m'; R='\033[31m'; D='\033[2m'; Y='\033[33m'; N='\033[0m'; else C=; G=; R=; D=; Y=; N=; fi
step() { printf "${C}==> %s${N}\n" "$1"; }
ok() { printf "${G}    %s${N}\n" "$1"; }
fail() {
    printf "${R}%s: %s${N}\n" "$(t Hata Error)" "$1" >&2
    [ -n "${2:-}" ] && printf "${D}%s: %s${N}\n" "$(t İpucu Hint)" "$2" >&2
    exit 1
}

find_uv() {
    if command -v uv >/dev/null 2>&1; then command -v uv; return; fi
    for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -x "$candidate" ]; then echo "$candidate"; return; fi
    done
}

UV=$(find_uv || true)

if [ "$UNINSTALL" = 1 ]; then
    [ -n "$UV" ] || fail "$(t "uv bulunamadı; gitex zaten kurulu görünmüyor." "uv not found; gitex does not seem to be installed.")"
    step "$(t "gitex kaldırılıyor" "Uninstalling gitex")"
    "$UV" tool uninstall gitex
    ok "$(t "Kaldırıldı. Anahtar kasasındaki kayıtlar için önce: gitex auth logout" "Removed. To clear stored keys first run: gitex auth logout")"
    exit 0
fi

step "$(t "git kontrol ediliyor" "Checking git")"
command -v git >/dev/null 2>&1 || fail "$(t "git bulunamadı." "git not found.")" "$(t "Kurun" "Install it"): https://git-scm.com/downloads"
ok "$(git --version)"

if [ -z "$UV" ]; then
    step "$(t "uv kuruluyor (Python ve paket yöneticisi, astral.sh)" "Installing uv (Python and package manager, astral.sh)")"
    [ "$MODIFY_PATH" = 1 ] || export UV_NO_MODIFY_PATH=1
    NET_HINT="$(t "İnternet bağlantısını kontrol edin" "Check your internet connection"): https://docs.astral.sh/uv/"
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh || fail "$(t "uv indirilemedi." "Could not download uv.")" "$NET_HINT"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh || fail "$(t "uv indirilemedi." "Could not download uv.")" "$NET_HINT"
    else
        fail "$(t "uv'yi indirmek için curl ya da wget gerekli." "curl or wget is required to download uv.")"
    fi
    UV=$(find_uv || true)
    [ -n "$UV" ] || fail "$(t "uv kuruldu ama bulunamadı." "uv was installed but cannot be found.")" "$(t "Yeni bir terminal açıp bu betiği tekrar çalıştırın." "Open a new terminal and run this script again.")"
fi
ok "uv: $("$UV" --version)"

step "$(t "Python 3.12 ve gitex kuruluyor (ilk seferde birkaç dakika sürebilir)" "Installing Python 3.12 and gitex (the first time can take a few minutes)")"
"$UV" tool install --force --python 3.12 "$ROOT" \
    || fail "$(t "gitex kurulamadı." "gitex could not be installed.")" "$(t "Yukarıdaki hatayı kontrol edin; bu betiği tekrar çalıştırmak güvenlidir." "Check the error above; re-running this script is safe.")"

BIN_DIR=$("$UV" tool dir --bin)
if [ "$MODIFY_PATH" = 1 ]; then
    "$UV" tool update-shell >/dev/null 2>&1 || true
fi
PATH="$BIN_DIR:$PATH"
export PATH
[ -x "$BIN_DIR/gitex" ] || fail "$(t "gitex komutu bulunamadı" "gitex command not found"): $BIN_DIR/gitex"
ok "$("$BIN_DIR/gitex" --version) $(t kuruldu installed) → $BIN_DIR/gitex"

# Seçilen dili kaydet; gitex'in bütün mesajları bu dilde olur.
"$BIN_DIR/gitex" config set ui.language "$GX_LANG" --global >/dev/null 2>&1 || true

echo
if [ "$SETUP" = 1 ] && [ -t 0 ]; then
    step "$(t "Kurulum sihirbazı başlatılıyor (model, API anahtarı, GitLab)" "Starting the setup wizard (model, API key, GitLab)")"
    "$BIN_DIR/gitex" setup --lang "$GX_LANG" || true
fi

echo
printf "${G}%s${N}\n" "$(t "Kurulum tamam." "Installation complete.")"
echo "  $(t "Başlamak için bir git deposunda:  gitex ask \"Son değişiklikler neler?\"" "To start, inside a git repository:  gitex ask \"What changed recently?\"")"
echo "  $(t "Ayarlar: gitex setup  ·  Kontrol: gitex doctor  ·  Tüm komutlar: gitex --help" "Settings: gitex setup  ·  Check: gitex doctor  ·  All commands: gitex --help")"
if [ "$MODIFY_PATH" = 0 ]; then
    echo "  $(t "PATH değiştirilmedi; komut" "PATH was not changed; command"): $BIN_DIR/gitex"
else
    # Bir alt süreç, kendisini başlatan kabuğun PATH'ini değiştiremez.
    case ":$CALLER_PATH:" in
        *":$BIN_DIR:"*) ;;
        *)
            echo
            printf "${Y}  %s${N}\n" "$(t "ÖNEMLİ: Bu terminal gitex'i henüz tanımıyor." "IMPORTANT: this terminal does not know about gitex yet.")"
            printf "${Y}  %s${N}\n" "$(t "Terminali kapatıp yeniden açın — ya da bu pencerede hemen kullanmak için:" "Close and reopen the terminal — or run this to use it here right away:")"
            echo "    export PATH=\"$BIN_DIR:\$PATH\""
            ;;
    esac
fi
