# Putting Tuki online (PythonAnywhere, step by step)

PythonAnywhere runs Python sites and keeps your files (database, photos), so accounts and orders stay saved.
A free account gives you `yourusername.pythonanywhere.com` with HTTPS. Your own domain (like tukibd.com) needs a paid plan.
Check their site for current plans and limits before you start.

1. Make an account at pythonanywhere.com.
2. **Files** tab: upload `tuki-shop.zip` to your home folder.
3. **Consoles** tab, start a **Bash** console, then run:
   ```
   unzip tuki-shop.zip
   cd tuki-shop
   python3 -m venv ~/tuki-env
   source ~/tuki-env/bin/activate
   pip install -r requirements.txt
   python app.py create-admin
   ```
   (choose your admin username and a strong password of 12+ characters)
4. **Web** tab: **Add a new web app**, choose **Manual configuration** and a Python version (3.10 or newer).
5. On the Web tab set **Virtualenv** to `/home/YOURUSERNAME/tuki-env`.
6. On the Web tab open the **WSGI configuration file**, delete everything in it and paste:
   ```python
   import os, sys
   path = "/home/YOURUSERNAME/tuki-shop"
   if path not in sys.path:
       sys.path.insert(0, path)
   os.environ["TUKI_HTTPS"] = "1"
   os.environ["TUKI_PROXY"] = "1"
   os.environ["TUKI_SECRET_KEY"] = "PASTE-A-LONG-RANDOM-TEXT-HERE"
   os.environ["TUKI_ADMIN_PATH"] = "pick-your-secret-door-name"
   from app import app as application
   ```
   Replace YOURUSERNAME. For the secret key, make a long random text (60+ characters).
7. On the Web tab press the green **Reload** button, then open `https://YOURUSERNAME.pythonanywhere.com`.
8. Admin login: `https://YOURUSERNAME.pythonanywhere.com/pick-your-secret-door-name/login` (or tap the shop name 3 times).
9. In **Settings** in the admin, add your phone, WhatsApp and Facebook, and in **Products** add your products.
10. Web tab, **Security** section: switch on **Force HTTPS**.

Every week press **Download backup** in the admin (Security tab) and keep the zip safe.
Check the PythonAnywhere Web tab now and then, free sites may need a renew button pressed.

If something shows an error, open the **Error log** link on the Web tab and send me the last lines.
