# External Sources for Baseline-Import Backup and Recovery

PostgreSQL describes three backup approaches—SQL dump, file-system-level backup, and continuous archiving—each with different recovery properties. `pg_dump` creates consistent logical exports during concurrent use but is not generally the regular production-backup mechanism for a full cluster; its custom and directory formats support flexible `pg_restore` workflows. [1] [2]

For physical backups, PostgreSQL’s `pg_verifybackup` checks a base-backup manifest, file presence/size, checksums, and required WAL readability. The documentation explicitly states that this verification does not prove every recovery condition and recommends test restores to validate the resulting database and data. [3]

Continuous archiving combines a base backup with archived WAL to support point-in-time recovery, but successful recovery requires a continuous sequence of WAL files that reaches back to the base backup start. PostgreSQL recommends testing the archiving procedure before taking the first base backup and monitoring archive failures or lag. [4]

## References

[1] [PostgreSQL, *Backup and Restore*](https://www.postgresql.org/docs/current/backup.html)

[2] [PostgreSQL, *pg_dump*](https://www.postgresql.org/docs/current/app-pgdump.html)

[3] [PostgreSQL, *pg_verifybackup*](https://www.postgresql.org/docs/current/app-pgverifybackup.html)

[4] [PostgreSQL, *Continuous Archiving and Point-in-Time Recovery*](https://www.postgresql.org/docs/current/continuous-archiving.html)
