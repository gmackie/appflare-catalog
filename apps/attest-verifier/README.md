# Install the Attest verifier

This Worker verifies presentations and signs results. Choose Workers Paid for the configured CPU budget. Enrollments and replay protection use storage in the installing account.

1. Choose the final HTTPS origin. Set the verifier ID to that origin.
2. Generate your result-signing key on your own computer with Node using the pinned release's key generator. Save stdout directly to a private password manager or a new mode-0600 file. Stdout is the complete private JSON for the Appflare secret. Stderr contains the public JWK that relying parties pin. Keep both across updates. [Key generator](https://github.com/gmackie/attest/blob/5de9ae73a2547dc11ba21bd79e8bf3b734670dc7/apps/verifier/scripts/new-result-key.mjs)
3. Enter your trusted presentation issuers and their public P-256 keys in `TRUSTED_PEPS`. Configure `IDENTITY_PROVIDERS` with the expected issuer, JWKS URI and audience for enrollment. Enter browser origins as a JSON array. [Configuration format](https://github.com/gmackie/attest/blob/5de9ae73a2547dc11ba21bd79e8bf3b734670dc7/apps/verifier/src/config.ts)
4. Supply HTTPS URLs from two independent Sepolia RPC providers. Include provider API keys only in the secret fields. Preserve the finalized-block setting unless your trust policy specifies another value.
5. Check `/health` for a successful configuration and provider check. Exercise a synthetic enrollment and presentation with your own relying party, then submit the same presentation again and confirm the replay is rejected.

Original Attest verifier code is licensed under Apache-2.0. The combined executable is licensed under GPL-3.0-only. Download the matching `attest-verifier-source.tar.gz` alongside each signed release for its corresponding source, build instructions and third-party notices. [This release](https://github.com/gmackie/appflare-catalog/releases/tag/attest-verifier%400.0.0-20261123.5de9ae7)
