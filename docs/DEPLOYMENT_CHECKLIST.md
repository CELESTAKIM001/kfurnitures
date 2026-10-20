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
