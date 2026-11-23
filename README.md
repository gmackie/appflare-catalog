# Graham Mackie's Appflare catalog

Install these applications into your own Cloudflare account with Appflare. In **Settings → Catalogs → Add catalog**, enter the following values and compare the fingerprint before confirming.

| Setting | Value |
| --- | --- |
| Index URL | `https://gmackie.github.io/appflare-catalog/index.json` |
| Public key | `{"keyId":"gmackie-2026-11","publicKeyBase64":"TyBeWpgDb2pATcAHa5ecP1/jYqcOX/XE82VDZ6UprZw="}` |
| SHA-256 fingerprint | `SHA256:JJUnjF+/5o6p3mX0hQZ8u7ksOcVTaHLvMGFyeV9/CAA` |

- [Nathan identity provider](apps/nathan-idp/README.md) is an experimental identity provider. Its first owner verifies a provider identity and enrolls authenticators.
- [Worker CRM](https://github.com/gmackie/worker-crm) stores people, companies, opportunities and tasks in D1 and serves the Twenty API routes used by Pulse.

Each entry pins a source revision. Release builds run without the signing key, and a separate step signs the resulting artifact. An installation creates resources in the account the operator selects.

[Set up Appflare](https://appflare.dev/start/install/) · [Custom catalogs](https://appflare.dev/guides/custom-catalogs/) · [Upstream catalog template](https://github.com/appflare/catalog/blob/main/TEMPLATE.md)
