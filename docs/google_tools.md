# Google tool compatibility

The Python runner does not authenticate to Google. The Codex operator executes queued operations with connected tools, saves their complete actual JSON results locally, and acknowledges them to the runner. Model workers never publish to Google.

Availability depends on the user's Codex installation, connectors, account and permissions. Connecting a generic read-only Drive tool is insufficient. The current bridge names tools with the `mcp__codex_apps__google_drive_` prefix and expects the corresponding argument/result schemas. An arbitrary MCP server with similarly named tools is not automatically compatible.

Required capabilities include:

- `import_spreadsheet`: import the bundled blank XLSX as native Google Sheets, accepting a local `source_file`, `title` and `upload_mode=native_google_sheets`.
- `get_spreadsheet_metadata`, `get_spreadsheet_cells`, `batch_update_spreadsheet`: identify the tab/grid, read exact cells and update ranges/grid sizes with independent readback.
- `import_document`: import a locally generated report as a native Google Doc.
- `get_document`, `batch_update_document`: read complete document/tab content and revision identity; create/update native tabs, text, headings and tables.
- `get_file_metadata`, `copy_file`: verify native file identity and make backups when an explicitly requested revision requires them.

The active queued request is authoritative for exact tool name, arguments and expected response. Results must provide actual native MIME, matching file IDs/URLs, cell values or document content as requested. HTML previews, exported Office files and invented acknowledgements cannot substitute for native creation/readback. The connector must support the native Docs tab operations used by `document_tabs.py`.

Before starting research, the operator should inspect available tool definitions for these capabilities and confirm the authenticated user can create, read and update their own output files. Do not request broad organizational access. If tools or permissions are missing, stop and explain what is unavailable; do not build OAuth, use a browser login workaround or claim publication succeeded.

Offline tests simulate these operations and validate the runner's contracts. They do not establish live connector availability, schemas, permissions, document rendering or current CLI/account compatibility. No live integration is certified by this release preparation.
