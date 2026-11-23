# Install Nathan identity

This preview installs the identity Worker, one D1 database and the SCIM Durable Object. Pick a permanent issuer hostname before creating a passkey. Nathan scopes passkeys to that hostname.

1. In your Appflare manager, select **Nathan identity provider**. Choose the Worker name and hostname. Register a Google OAuth web client for that hostname. Its authorized redirect URI is `https://YOUR-ISSUER/api/auth/callback/google`.
2. Enter the client ID, client secret and the single Google-verified owner email. Generate the configuration encryption key according to the install form and keep a recovery copy. Appflare creates a pending owner record and applies the migrations.
3. Open `/sign-in` on the issuer and sign in as that owner. For first enrollment the operator also proves control of the Cloudflare account by promoting the verified user through Nathan's CLI.
4. Use Node 22.13 or later. From the source checkout below, create `nathan.config.json` using your account ID, issuer hostname, owner email and the D1 database name shown in Appflare. Grant a scoped Cloudflare API token D1 read/write in that account and supply it through your local credential manager as `CLOUDFLARE_API_TOKEN`.

```sh
git clone https://github.com/gmackie/nathan.git
cd nathan
git checkout 45220e2caccaa311fad5e4ea98d557c5311428b3
npm ci
```

```json
{
  "name": "nathan-idp",
  "hostname": "login.example.org",
  "securityProfile": "business",
  "accountId": "YOUR_32_CHARACTER_ACCOUNT_ID",
  "database": { "type": "d1", "name": "YOUR_INSTALLED_D1_NAME" },
  "adminEmails": ["owner@example.org"],
  "applications": []
}
```

5. Run `node scripts/nathan.mjs admin promote --apply nathan.config.json` and confirm the owner’s email. A retry with the same identity preserves existing enrollment.
6. Open `/security?setup=admin` on the issuer. Enroll a passkey and TOTP, save the recovery codes, and finish setup. Sign in with the passkey to enter Identity Studio.
7. Confirm `/api/auth/.well-known/openid-configuration` advertises your issuer, then register a test client and complete an authorization-code sign-in with PKCE.

The publisher has verified packaging and D1 migrations locally. Test owner enrollment and relying-party sign-in in your own disposable install before using this experimental identity provider for production authentication.
