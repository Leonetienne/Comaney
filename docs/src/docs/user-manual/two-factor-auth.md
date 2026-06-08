# Two-Factor Authentication

Two-factor authentication (2FA) adds an extra layer of security to your account. After you enter your password, Comaney asks you to confirm your identity a second way. Even if someone learns your password, they still cannot log in without that second step.

Comaney supports three kinds of second step, and you can set up any number of them:

- **Authenticator app**: a 6-digit code from an app on your phone.
- **Security key**: a physical key (such as a YubiKey), or your device's built-in fingerprint or face unlock (Touch ID, Windows Hello). This is also known as a FIDO2 or WebAuthn key.
- **Email code**: a 6-digit code sent to your account's email address whenever you need it. This option only shows up if the Comaney instance you're using is set up to send email; if you don't see it, ask whoever runs your instance.

You only need one method to protect your account. Adding a second one is useful as a backup in case you lose the first.

## What you need

For an authenticator app, a free app on your smartphone:

- **Google Authenticator** (iPhone or Android)
- **Authy** (iPhone, Android, or desktop)
- Your password manager if it supports one-time codes (1Password, Bitwarden, and others do)

For a security key:

- A FIDO2/WebAuthn-compatible physical key, or
- A device with a built-in authenticator, such as Touch ID or Windows Hello

## Setting up an authenticator app

1. Go to **Account Settings** and find the **Two-factor authentication** section.
2. Click **Add new second factor**, then choose **Authenticator app** from the menu.
3. Open your authenticator app and scan the QR code shown on the screen.
4. Give it a name (for example "Phone" or "Google Authenticator") so you can tell it apart from any other authenticator app you add later.
5. The app will immediately start showing a 6-digit code that changes every 30 seconds. Enter the current code to confirm that the setup worked.
6. Click **Activate**.

## Setting up a security key

1. Go to **Account Settings** and find the **Two-factor authentication** section.
2. Click **Add new second factor**, then choose **Security key** from the menu.
3. Give the key a name (for example "Work YubiKey" or "MacBook Touch ID") so you can tell it apart later.
4. Click **Register security key** and follow your browser's prompt to tap, insert, or scan your key.

## Setting up an email code

1. Go to **Account Settings** and find the **Two-factor authentication** section.
2. Click **Add new second factor**, then choose **Email code** from the menu. (If you don't see this option, your Comaney instance isn't set up to send email.)
3. Comaney immediately emails a 6-digit code to your account's address. Enter it to confirm that the setup worked.
4. If the email doesn't arrive within a minute, click **Resend code**.
5. Click **Activate**.

You can only have one email code method on your account, since it always goes to the same address. There's no separate "name" step for it the way there is for authenticator apps and security keys.

!!! warning "Save your recovery code"
    The first time you set up a second-factor method, Comaney shows you a **recovery code**. Copy it and store it somewhere safe (a password manager, or a printed note kept somewhere secure).

    If you ever lose access to every method you've set up, the recovery code is the only way to get back into your account. It is shown only once, and adding further methods later does not generate a new one.

## Using more than one method

You can set up an authenticator app and one or more security keys on the same account. Whichever one is marked **Primary** is what you're asked for first when you log in.

When you add a second or later method, a checkbox lets you make it the new primary method. If you leave it unchecked, your existing primary method stays as it is. You can also change which method is primary at any time from **Account Settings**, using **Set as primary** next to any method in the list.

## Logging in with 2FA

After you enter your email and password, a second screen asks you to confirm with your primary method: either a 6-digit code from your authenticator app, or a prompt to use your security key.

If you have more than one method set up and the one shown isn't available to you right now, click **Try a different method** to pick another one.

## If you lose access to all of your methods

1. On the login screen, after entering your password, click **Lost access? Use a recovery code**.
2. Enter the recovery code you saved during setup.
3. You are logged in, and every second-factor method on your account is removed.

Because using the recovery code removes all of your methods at once, only use it when you genuinely cannot reach any of them. After recovering access, set up 2FA again to get a fresh recovery code.

## Managing your methods

The **Two-factor authentication** section of **Account Settings** lists every method on your account, showing its name, when it was added, and whether it's the primary one. From there you can:

- **Rename**: click a method's name to edit it in place, then press Enter (or click away) to save. This is handy if you own several security keys with the same name and want to tell them apart, for example by writing the ID printed on the key itself.
- **Test**: opens a page where you can try that specific method on its own, without logging out. This lets you figure out which physical key or authenticator entry a method actually corresponds to before renaming it.
- **Set as primary**: make a method the one you're asked for first at login.
- **Remove**: delete a method. If you have another method, you'll be asked to confirm with it first. If it's your only method, removing it turns 2FA off entirely.
- **Regenerate recovery code**: get a new recovery code if you've lost the old one, or simply want a fresh one. You'll need to confirm with one of your existing methods first, and your old recovery code stops working immediately.
