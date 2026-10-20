# KIMATHI Furniture — Flask / Vercel starter

Responsive furniture storefront using the supplied KIMATHI brand images and MP4 logo films, Flask routes, MongoDB Atlas persistence, an admin dashboard, expense logging, order tracking, printable receipts, SMTP email, optional checkout email OTP, and Daraja STK push integration.

## Deploy to Vercel

1. Upload this folder to a new GitHub repository.
2. Import that repository in Vercel. The included `vercel.json` routes requests through `api/index.py`.
3. In Vercel → Project → Settings → Environment Variables, add the variables from `.env.example`. Do not commit a real `.env`.
4. Create a MongoDB Atlas database user and allow network access for your deployment. Use the complete Atlas connection URI including the password and database name. Keep the password URL-encoded if it contains special characters.
5. Set `SECRET_KEY` and `CRON_SECRET` to long, unique random values. Set `ADMIN_PASSWORD` to a strong unique password before deployment.
6. Set `FRONTEND_URL`, `PUBLIC_APP_URL`, and `MPESA_CALLBACK_URL` to the actual deployed HTTPS domain. Redeploy after changing environment variables.
7. Configure Daraja production credentials and the callback URL in the Safaricom portal. Test with an approved account and a low-value transaction before launch.
8. Configure Gmail SMTP with an App Password (if using a Google account with 2-Step Verification). Never use your normal Gmail login password.
9. Visit `/health` and `/admin/login` after deployment.

## M-Pesa configuration note

`MPESA_BUSINESS_SHORT_CODE` and `MPESA_VENDOR_TILL` are kept as separate environment values. The STK request uses the shortcode for the Daraja password and `PartyB` is populated from the configured till. This field combination must match the exact Daraja product and shortcode/till configuration approved by Safaricom; do not assume a Till number can be used as `PartyB` for every shortcode setup. Production STK push cannot be verified without valid credentials, an approved shortcode/passkey, and a reachable HTTPS callback.

The payment screen does not collect an M-Pesa PIN. The application only requests the Safaricom prompt and marks an order paid after a callback. In production, add callback signature/IP validation, idempotency checks, transaction reconciliation, and alerting before accepting real payments.

## Features in this starter

- Responsive catalogue with filters, product details, cart, checkout and progress feedback.
- MongoDB-backed orders, expense entries, visitor events, payment events, campaign logs and editable contact/location/OTP settings.
- Optional email OTP before payment (`PURCHASE_EMAIL_OTP_ENABLED=false` initially; admin can toggle after SMTP works).
- M-Pesa STK push endpoint and callback handler.
- Printable receipt with logo, public order tracking that hides customer contact details, and CSV exports for admin.
- Admin password stored only in environment variables.
- Supplied image assets and logo-reveal MP4s are retained in `static/`.

## Important production gaps

This is a functional starter, not a certified or fully audited commerce platform. The product catalogue is currently configured in code, stock is not decremented, expense records are not automatically allocated to item-level cost of goods, and inventory/profit reports are not complete. Public order references should be upgraded to signed/unguessable tracking tokens and receipt access should require a customer verification link. Add rate limiting, CSRF protection for form actions, robust admin MFA, spam controls, validated callback reconciliation, and automated tests before public production use. Vercel functions are stateless; persistent data must be stored in MongoDB or another external database, never local files.
