# Two-Factor Authentication

Two-factor authentication (2FA) adds an extra layer of security to your account. After you enter your password, Comaney asks for a 6-digit code from an app on your phone. Even if someone learns your password, they still cannot log in without that code.

## What you need

A free authenticator app on your smartphone. Popular options:

- **Google Authenticator** (iPhone or Android)
- **Authy** (iPhone, Android, or desktop)
- Your password manager if it supports one-time codes (1Password, Bitwarden, and others do)

Any of these will work.

## Setting up 2FA

1. Go to **Account Settings** and find the **Two-factor authentication** section.
2. Click **Set up 2FA**.
3. Open your authenticator app and scan the QR code shown on the screen.
4. The app will immediately start showing a 6-digit code that changes every 30 seconds. Enter the current code to confirm that the setup worked.
5. Click **Save**.

!!! warning "Save your recovery code"
    After setup, Comaney shows you a **recovery code**. Copy it and store it somewhere safe (a password manager, a printed note kept somewhere secure).

    If you ever lose your phone or cannot access your authenticator app, the recovery code is the only way to get back into your account. It is shown only once.

## Logging in with 2FA

After you enter your email and password, a second screen asks for your 6-digit code. Open your authenticator app, find the Comaney entry, and type in the code shown.

The code changes every 30 seconds. If you enter a code and it is rejected, simply wait for the next one to appear and try again.

## If you lose your phone

1. On the login screen, after entering your password, click **Use recovery code**.
2. Enter the recovery code you saved during setup.
3. You are logged in and 2FA is disabled on your account.

After recovering access, set up 2FA again to get a fresh recovery code.

## Turning off 2FA

1. Log in to your account (using your code if 2FA is currently active).
2. Go to **Account Settings** and find the **Two-factor authentication** section.
3. Click **Disable 2FA** and confirm.

2FA is removed immediately.
