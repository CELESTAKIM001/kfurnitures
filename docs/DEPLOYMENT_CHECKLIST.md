# Launch checklist

- [ ] Replace all example/blank environment variables in Vercel.
- [ ] Confirm MongoDB Atlas credentials, database name, network access and persistence.
- [ ] Use a strong `SECRET_KEY`, `CRON_SECRET`, and `ADMIN_PASSWORD`.
- [ ] Verify admin access and all CSV exports.
- [ ] Test SMTP send, OTP expiry and wrong-code handling.
- [ ] Configure Safaricom Daraja production credentials, shortcode, passkey and callback.
- [ ] Verify callback receipt metadata and repeated callback handling.
- [ ] Confirm the actual business account supports the configured STK `TransactionType` and PartyB/Till combination.
- [ ] Test stock changes, refunds, cancelled/failed transactions, partial payments and order reconciliation (not implemented in this starter).
- [ ] Add rate limiting, CSRF tokens, MFA, monitoring, backups and privacy notice before launch.
- [ ] Confirm receipts show PAID only after a verified provider callback.

- [ ] Set `ADMIN_PATH` to a long private path and `ADMIN_PASSWORD` to a strong unique password; public `/admin` and `/admin/login` paths should return 404. The storefront navigation intentionally has no Admin link.
- [ ] Confirm `https://YOUR-PRODUCTION-DOMAIN/api/mpesa/callback` opens and returns JSON indicating the callback endpoint is reachable (GET health check). Set that exact URL as `MPESA_CALLBACK_URL` in Vercel.
- [ ] Set `PUBLIC_APP_URL` to `https://kfurnitures.vercel.app` (or the actual primary production domain), then redeploy. Avoid deployment-protected preview URLs for Daraja callbacks.
- [ ] If checkout or admin still returns a 5xx response, inspect Vercel Runtime Logs for the same request and use the traceback to diagnose it. Never share secret environment variable values.
