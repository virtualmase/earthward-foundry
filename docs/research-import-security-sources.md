# External Security Sources for the Baseline-Import Threat Model

## PostgreSQL row-level security

PostgreSQL documents that enabled row-security policies constrain ordinary reads and data modifications, with a default-deny result when no policy applies. The documentation also notes that superusers and roles with `BYPASSRLS` bypass RLS, table owners normally bypass it unless `FORCE ROW LEVEL SECURITY` is used, and referential-integrity checks can create covert-channel concerns. These details support the dedicated non-owner/no-`BYPASSRLS` runtime roles, `FORCE ROW LEVEL SECURITY`, composite tenant keys, and controlled error behavior in the workspace design. [1] [2]

## Upload and REST API controls

OWASP recommends defense in depth for uploads: allow-list types, do not trust client `Content-Type`, generate storage names, limit filename and file size, authorize uploaders, isolate files from the web root, and scan or sandbox files where feasible. It also identifies malicious archives and decompression-based resource exhaustion as upload threats. [3]

OWASP’s REST guidance recommends HTTPS, per-endpoint authorization, server-side workflow-state validation, explicit content-type/size validation, generic safe error responses, and audit logging around security events. The OWASP API Security Top 10 highlights object-level authorization, function-level authorization, resource exhaustion, sensitive-business-flow abuse, security misconfiguration, and unsafe consumption as relevant API risks. [4] [5]

## References

[1] [PostgreSQL 18, *Row Security Policies*](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)

[2] [PostgreSQL 18, *CREATE POLICY*](https://www.postgresql.org/docs/current/sql-createpolicy.html)

[3] [OWASP Cheat Sheet Series, *File Upload Cheat Sheet*](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)

[4] [OWASP Cheat Sheet Series, *REST Security Cheat Sheet*](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html)

[5] [OWASP API Security Project, *Top 10 API Security Risks—2023*](https://owasp.org/API-Security/editions/2023/en/0x11-t10/)
