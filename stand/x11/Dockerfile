# X11 test stand of browser-selector: an X server without a screen, a small
# EWMH window manager and the same link opening chain as on the desktop
# (xdg-open -> gio open -> the default handler). Ubuntu 22.04 carries what the
# desktop of the user runs: python 3.10, xdg-utils 1.1.3, GLib 2.72, GTK 4.6
# and libadwaita 1.1 for the picker and the settings window. xdotool types
# and clicks in those windows, the font is what GTK draws them with.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-tk \
        python3-gi \
        gir1.2-gtk-4.0 \
        gir1.2-adw-1 \
        fonts-dejavu-core \
        xdotool \
        xvfb \
        openbox \
        x11-utils \
        wmctrl \
        xdg-utils \
        libglib2.0-bin \
        dbus \
        procps \
        strace \
    && rm -rf /var/lib/apt/lists/*

# Same uid as the developer on the host, so the logs in the mounted out/ are
# owned by the developer. The container itself starts as root for one step,
# the cgroup delegation in inner.sh, and runs everything else as this user.
ARG UID=1000
RUN useradd -u "$UID" -m dev

CMD ["/bin/bash"]
