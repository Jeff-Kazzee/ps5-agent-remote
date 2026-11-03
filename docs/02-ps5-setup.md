# 2. PS5 setup

You do this once. Have the PS5 on and the remote page open
(http://127.0.0.1:8765).

## 2.1 Turn on Remote Play

On the PS5:

1. **Settings > System > Remote Play**
2. Turn on **Enable Remote Play**.

## 2.2 Let the computer wake the PS5 (optional, recommended)

Without this, the **Power on** button and the agent's `ps5_power on` can't
wake the console from rest mode.

1. **Settings > System > Power Saving > Features Available in Rest Mode**
2. Turn on **Stay Connected to the Internet**.
3. Turn on **Enable Turning On PS5 from Network**.

## 2.3 Sign in and link this computer

The remote page shows a setup card until this is done.

### Step 1: sign in to PlayStation Network

The server needs your PSN account ID to link, and the sign-in also turns on
the library and store search.

1. In your normal browser, go to https://www.playstation.com and **Sign In**
   (top right) with the account you use on the PS5.
2. In the same browser, open
   https://ca.account.sony.com/api/v1/ssocookie
3. The page shows one line like `{"npsso":"Ab12...xyz"}`. Copy the whole line.
4. Paste it into **step 1** on the remote page and click **Save**.
   The page says **Signed in as** your PSN name.

That 64-character `npsso` value is a sign-in token for your account.

- Don't paste it anywhere else. Anyone with it can read your account.
- It is saved in `.env.local` in the project folder, which git ignores.
- It lasts about two months. When PSN lookups start failing, repeat these
  steps.
- Getting a new one signs out the old one. Signing out of playstation.com
  in that browser can also end it, so stay signed in after you copy it.

### Step 2: link with a PIN

1. On the PS5: **Settings > System > Remote Play > Link Device**.
   The PS5 shows an 8-digit number.
2. Type it into **step 2** on the remote page and click **Link**.
   The PIN expires after a few minutes. If it does, start again.
3. The page says **Linked** and the setup card disappears.

The link keys are saved in `C:\Users\<you>\.ps5-remote\consoles.json`.
Keep that file private. It lets this computer control your PS5.

### Test it

Press a D-pad button on the page and watch the TV. Then tick **Live view**.
You should see the PS5 screen in the browser within a few seconds.

## 2.4 Recommended: require a password for purchases

This makes it impossible for anyone using the remote, including an agent,
to finish a purchase without your PSN password.

1. **Settings > Users and Accounts > Account > Payment and Subscriptions >
   Purchase Settings**
2. Turn on **Require Password at Checkout**.

## 2.5 More than one PS5

The server finds the PS5 on its own by asking the network. With several
consoles it picks the linked one. To point it at a specific console, set its
IP address before starting:

```powershell
$env:PS5_HOST = "192.168.1.50"
.\start.cmd
```

Or put `PS5_HOST=192.168.1.50` in `.env.local`. To find the console's
address, run `.venv\Scripts\python.exe ddp.py`, or look in
**Settings > Network > Connection Status > View Connection Status** on the
PS5.

Next: [3. Agents](03-agents.md) or [4. Using the remote](04-using-the-remote.md)
