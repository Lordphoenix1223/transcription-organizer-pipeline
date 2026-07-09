# Security Policy

This repository contains a local transcription pipeline and sample artifacts only. It should never contain real recordings, private transcripts, secrets, internal database IDs, or customer data.

## Reporting

- Prefer GitHub private vulnerability reporting if it is enabled for this repository.
- If private reporting is not available, open a minimal issue requesting contact and keep the report high level.
- Do not post API keys, Notion tokens, database IDs, local filesystem paths, or real interview material in issues or pull requests.

## Scope Notes

- There is no public API surface and no network service exposed by this repository.
- The main risks here are secret leakage, unsafe publication of customer data, dependency hygiene, and careless file handling.
