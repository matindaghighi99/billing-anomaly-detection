"""backup.py — Integrity-checked snapshots of the audit trail and case state.

Creates a timestamped copy of the tamper-evident audit log (after verifying its
hash chain) and the case-management store. BACKUP_DIR can point at a mounted
managed volume; for off-host durability, sync that directory to object storage
(S3 / Azure Blob / GCS) on a schedule — see DEPLOY.md. Run from cron / a
scheduled job:  python backup.py
"""

import datetime
import os
import shutil

try:
    from config import AUDIT_DB_PATH, CASE_DB_PATH, BACKUP_DIR
except Exception:
    AUDIT_DB_PATH = os.environ.get("AUDIT_DB_PATH", "audit_log.db")
    CASE_DB_PATH  = os.environ.get("CASE_DB_PATH", "audit_cases.db")
    BACKUP_DIR    = os.environ.get("BACKUP_DIR", "backups")


def run_backup(verify: bool = True) -> dict:
    """Snapshot the audit + case stores into a timestamped backup folder.

    Returns a status dict. If verify=True, the audit hash chain is checked first
    and a failure is reported (the backup still proceeds so forensic copies exist).
    """
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(BACKUP_DIR, ts)
    os.makedirs(dest, exist_ok=True)

    status = {"timestamp": ts, "dest": dest, "files": [], "integrity": None}

    if verify and os.path.exists(AUDIT_DB_PATH):
        try:
            import audit_log
            res = audit_log.verify_integrity()
            status["integrity"] = res.get("ok")
            status["integrity_message"] = res.get("message")
        except Exception as exc:
            status["integrity"] = False
            status["integrity_message"] = f"verify failed: {exc}"

    for src in (AUDIT_DB_PATH, CASE_DB_PATH):
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
            status["files"].append(os.path.basename(src))

    # Also export the audit log to CSV for human-readable archival.
    try:
        import audit_log
        audit_log.export_to_csv(os.path.join(dest, "audit_log_export.csv"))
        status["files"].append("audit_log_export.csv")
    except Exception:
        pass

    return status


def main():
    print("Audit/case backup")
    print("=" * 60)
    status = run_backup()
    print(f"  Destination : {status['dest']}")
    print(f"  Files       : {', '.join(status['files']) or '(none found)'}")
    print(f"  Integrity   : {status['integrity']}  {status.get('integrity_message','')}")
    print("  For off-host durability, sync this directory to object storage "
          "(S3/Azure Blob/GCS).")


if __name__ == "__main__":
    main()
