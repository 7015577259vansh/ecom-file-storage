import os
import io
import csv
import boto3
from flask import Flask, request, redirect, url_for, session, render_template_string, flash, send_file
from werkzeug.security import generate_password_hash, check_password_hash

# ---------- CONFIG ----------
PRIMARY_BUCKET = "ecom-primary-102322005"   # change if your bucket name differs
BACKUP_BUCKET  = "ecom-backup-102322005"    # change if your bucket name differs
AWS_REGION     = "us-east-1"

app = Flask(__name__)
app.secret_key = "change-this-secret-key"

s3 = boto3.client("s3", region_name=AWS_REGION)

# ---------- FAKE USER STORE (in-memory, for demo only) ----------
users = {}  # username -> password_hash

# ---------- TEMPLATES (inline, simple) ----------
BASE = """
<!doctype html>
<title>{{ title }}</title>
<style>
body{font-family:Arial;max-width:700px;margin:40px auto;padding:0 20px}
input,button{padding:8px;margin:5px 0;width:100%}
button{background:#ff9900;border:none;color:white;font-weight:bold;cursor:pointer}
table{width:100%;border-collapse:collapse;margin-top:15px}
td,th{border:1px solid #ccc;padding:8px;text-align:left}
.msg{background:#eef;padding:10px;margin:10px 0}
nav a{margin-right:15px}
</style>
<nav>
{% if session.get('user') %}
  Logged in as <b>{{ session['user'] }}</b> |
  <a href="{{ url_for('dashboard') }}">Dashboard</a>
  <a href="{{ url_for('logout') }}">Logout</a>
{% else %}
  <a href="{{ url_for('login') }}">Login</a>
  <a href="{{ url_for('signup') }}">Signup</a>
{% endif %}
</nav>
<hr>
{% with messages = get_flashed_messages() %}
  {% if messages %}
    {% for m in messages %}<div class="msg">{{ m }}</div>{% endfor %}
  {% endif %}
{% endwith %}
{{ body|safe }}
"""

def render(title, body):
    return render_template_string(BASE, title=title, body=body)

# ---------- AUTH ----------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        u = request.form["username"].strip()
        p = request.form["password"]
        if u in users:
            flash("Username already exists.")
        else:
            users[u] = generate_password_hash(p)
            flash("Signup successful. Please login.")
            return redirect(url_for("login"))
    body = """
    <h2>Signup</h2>
    <form method="post">
      <input name="username" placeholder="Username" required>
      <input name="password" type="password" placeholder="Password" required>
      <button type="submit">Signup</button>
    </form>
    """
    return render("Signup", body)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["username"].strip()
        p = request.form["password"]
        if u in users and check_password_hash(users[u], p):
            session["user"] = u
            return redirect(url_for("dashboard"))
        flash("Invalid credentials.")
    body = """
    <h2>Login</h2>
    <form method="post">
      <input name="username" placeholder="Username" required>
      <input name="password" type="password" placeholder="Password" required>
      <button type="submit">Login</button>
    </form>
    """
    return render("Login", body)

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*a, **kw):
        if "user" not in session:
            flash("Please login first.")
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper

# ---------- DASHBOARD ----------
@app.route("/")
@login_required
def dashboard():
    body = """
    <h2>Dashboard</h2>
    <ul>
      <li><a href="{{ url_for('upload_file') }}">Upload file to S3 (primary bucket)</a></li>
      <li><a href="{{ url_for('list_files') }}">List files in primary bucket</a></li>
      <li><a href="{{ url_for('list_versions') }}">List versions (versioning proof)</a></li>
      <li><a href="{{ url_for('product_ranking') }}">Product ranking (from products.csv)</a></li>
    </ul>
    """
    return render("Dashboard", render_template_string(body))

# ---------- FILE UPLOAD ----------
@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload_file():
    if request.method == "POST":
        f = request.files.get("file")
        if not f or f.filename == "":
            flash("No file selected.")
            return redirect(url_for("upload_file"))
        key = f.filename
        s3.upload_fileobj(f, PRIMARY_BUCKET, key)
        flash(f"Uploaded '{key}' to {PRIMARY_BUCKET}. It will replicate to {BACKUP_BUCKET} automatically.")
        return redirect(url_for("list_files"))
    body = """
    <h2>Upload file</h2>
    <form method="post" enctype="multipart/form-data">
      <input type="file" name="file" required>
      <button type="submit">Upload</button>
    </form>
    """
    return render("Upload", body)

# ---------- FILE DOWNLOAD ----------
@app.route("/download/<key>")
@login_required
def download_file(key):
    obj = s3.get_object(Bucket=PRIMARY_BUCKET, Key=key)
    return send_file(io.BytesIO(obj["Body"].read()), download_name=key, as_attachment=True)

# ---------- LIST FILES ----------
@app.route("/files")
@login_required
def list_files():
    resp = s3.list_objects_v2(Bucket=PRIMARY_BUCKET)
    items = resp.get("Contents", [])
    rows = "".join(
        f"<tr><td>{o['Key']}</td><td>{o['Size']} B</td><td>{o['LastModified']}</td>"
        f"<td><a href='{url_for('download_file', key=o['Key'])}'>Download</a></td></tr>"
        for o in items
    )
    body = f"""
    <h2>Files in {PRIMARY_BUCKET}</h2>
    <table><tr><th>Key</th><th>Size</th><th>Last Modified</th><th>Action</th></tr>
    {rows}
    </table>
    """
    return render("Files", body)

# ---------- VERSIONING PROOF ----------
@app.route("/versions")
@login_required
def list_versions():
    resp = s3.list_object_versions(Bucket=PRIMARY_BUCKET)
    versions = resp.get("Versions", [])
    rows = "".join(
        f"<tr><td>{v['Key']}</td><td>{v['VersionId']}</td><td>{v['LastModified']}</td>"
        f"<td>{'LATEST' if v.get('IsLatest') else ''}</td></tr>"
        for v in versions
    )
    body = f"""
    <h2>Object Versions in {PRIMARY_BUCKET}</h2>
    <table><tr><th>Key</th><th>Version ID</th><th>Last Modified</th><th>Latest?</th></tr>
    {rows}
    </table>
    """
    return render("Versions", body)

# ---------- PRODUCT RANKING (reads products.csv from S3) ----------
@app.route("/ranking")
@login_required
def product_ranking():
    try:
        obj = s3.get_object(Bucket=PRIMARY_BUCKET, Key="products.csv")
        content = obj["Body"].read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        products = list(reader)
        # rank by price descending (change key as needed)
        products.sort(key=lambda p: float(p.get("price", 0)), reverse=True)
    except Exception as e:
        flash(f"Could not load products.csv: {e}")
        products = []

    rows = "".join(
        f"<tr><td>{i+1}</td><td>{p.get('product_name','')}</td>"
        f"<td>{p.get('category','')}</td><td>{p.get('price','')}</td>"
        f"<td>{p.get('stock','')}</td></tr>"
        for i, p in enumerate(products)
    )
    body = f"""
    <h2>Product Ranking (by price)</h2>
    <table><tr><th>Rank</th><th>Name</th><th>Category</th><th>Price</th><th>Stock</th></tr>
    {rows}
    </table>
    """
    return render("Ranking", body)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
