# GNOME 50 test stand of browser-selector: a headless GNOME Shell on Wayland
# with its Xwayland, and the same link opening chain as on the desktop
# (xdg-open -> gio open -> the default handler). Ubuntu 26.04 carries what the
# desktop of the user runs after its upgrade: gnome-shell 50, xdg-utils 1.2,
# GLib 2.88, python 3.14.
FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive
# gnome-shell brings mutter and the software renderer of a headless run.
# xwayland is the X server the handler asks with xprop, python3-tk the X11
# client of the fake app, gir1.2-gtk-4.0 its native Wayland variant. The
# portal is installed so that a click could go through it: the launch path
# scenario checks that it does not. gir1.2-adw-1 is what the picker and the
# settings window need on top of GTK 4. For the screenshots: librsvg draws
# the SVG icons, Yaru and Ubuntu Sans are the icon theme and the font of the
# Ubuntu desktop, Papirus lends the icons the browser packages would install.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gnome-shell \
        xwayland \
        x11-utils \
        python3 \
        python3-tk \
        python3-gi \
        gir1.2-gtk-4.0 \
        gir1.2-adw-1 \
        librsvg2-common \
        yaru-theme-icon \
        papirus-icon-theme \
        fonts-ubuntu \
        xdg-utils \
        xdg-desktop-portal \
        xdg-desktop-portal-gnome \
        libglib2.0-bin \
        dbus \
        dbus-x11 \
        adwaita-icon-theme \
        fonts-cantarell \
        procps \
        strace \
    && rm -rf /var/lib/apt/lists/*

# Same uid as the developer on the host, so the logs in the mounted out/ are
# owned by the developer. Ubuntu ships a user on uid 1000 already. The
# container itself starts as root for one step, the cgroup delegation in
# inner.sh, and runs everything else as this user.
ARG UID=1000
RUN userdel -r ubuntu 2>/dev/null || true
RUN useradd -u "$UID" -m dev

CMD ["/bin/bash"]
