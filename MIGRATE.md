# Moving to a new VPS (any provider, ~10 minutes)

The whole stack is reproducible from this repo. Only `data/` (journal, cache)
and the GRYD site live outside git — those travel in one backup file.

## 1. On the OLD box — take the backup
    bash /opt/gim/infra/backup.sh
    # then from your Mac:
    scp root@OLD_IP:/root/strait-backup-*.tgz ~/Downloads/

## 2. On the NEW box — rebuild everything
    apt update && apt install -y git
    git clone https://github.com/aahilsathar/gulf-india-monitor.git /opt/gim
    bash /opt/gim/infra/setup.sh

## 3. Restore the data
    # from your Mac:
    scp ~/Downloads/strait-backup-*.tgz root@NEW_IP:/root/
    # on the new box:
    bash /opt/gim/infra/restore.sh /root/strait-backup-*.tgz

## 4. Repoint the address
If you use a free DuckDNS domain (recommended — see below), log into duckdns.org
and change the IP. Every bookmark, home-screen icon and link keeps working.
If you use the raw IP, update your bookmarks.

## Why DuckDNS
Five minutes once: create a subdomain at duckdns.org pointing at your current IP,
then always open the domain instead of the IP. VPS changes become invisible.

## Habit
Run `infra/backup.sh` and pull the file down whenever the journal has entries
you'd mind losing. The journal IS the asset — treat it like one.
