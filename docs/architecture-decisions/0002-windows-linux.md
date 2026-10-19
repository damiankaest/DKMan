# ADR 0002 · Windows 10 mit Linux-Laufzeit

Status: angenommen, Hostwahl nach Preflight. Windows 10 bleibt erste Zielplattform;
Linux-Container laufen in Ubuntu. Dauerbetrieb bevorzugt VM, Entwicklung optional
WSL2. Hyper-V hängt von Edition und Hardware ab, Home benötigt eine andere kompatible
VM-Lösung. Keine automatische Wahl oder Hostinstallation aus dieser Sitzung.

Der Stack bindet ausschließlich Loopback. Für VM-Zugriff zunächst SSH-Tunnel.
Kein öffentlicher Port, kein automatisches Firewall-/NAT-/Autostart-Setup.
Windows 10 benötigt gesonderte Wartungs-/Supportstrategie. Quellen und konkrete
Hostabnahme stehen in `docs/windows10-setup.md`.
