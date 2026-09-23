
from flask import Flask, request, jsonify, session, redirect, render_template, g
import os, csv, io
import psycopg
from psycopg.rows import dict_row
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import date
import resend

app = Flask(__name__, template_folder=".")
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE-ME-IN-PRODUCTION")
DATABASE_URL = os.environ.get("DATABASE_URL")
resend.api_key = os.environ.get("RESEND_API_KEY")

class DBWrap:
    def __init__(self):
        self.conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    def execute(self, sql, args=()):
        # Keep the existing application SQL style while using PostgreSQL.
        return self.conn.execute(sql.replace("?", "%s"), args)
    def executescript(self, sql):
        for stmt in sql.split(";"):
            stmt=stmt.strip()
            if stmt:
                self.conn.execute(stmt)
    def commit(self): self.conn.commit()
    def close(self): self.conn.close()

def db():
    if "db" not in g:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL no está configurada")
        g.db = DBWrap()
    return g.db

@app.teardown_appcontext
def close_db(exc):
    c = g.pop("db", None)
    if c: c.close()

def init_db():
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id SERIAL PRIMARY KEY,
      email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS accounts(
      id SERIAL PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name TEXT NOT NULL, kind TEXT NOT NULL, balance DOUBLE PRECISION NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS transactions(
      id SERIAL PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
      kind TEXT NOT NULL CHECK(kind IN ('income','expense')),
      amount DOUBLE PRECISION NOT NULL CHECK(amount >= 0),
      category TEXT NOT NULL, description TEXT, tx_date TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS budgets(
      id SERIAL PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      category TEXT NOT NULL, monthly_limit DOUBLE PRECISION NOT NULL
    );
    CREATE TABLE IF NOT EXISTS goals(
      id SERIAL PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name TEXT NOT NULL, target DOUBLE PRECISION NOT NULL, current DOUBLE PRECISION NOT NULL DEFAULT 0,
      target_date TEXT
    );
    CREATE TABLE IF NOT EXISTS recurring(
      id SERIAL PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind TEXT NOT NULL CHECK(kind IN ('income','expense')),
      name TEXT NOT NULL, amount DOUBLE PRECISION NOT NULL, category TEXT NOT NULL,
      day_of_month INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS investments(
      id SERIAL PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name TEXT NOT NULL, units DOUBLE PRECISION NOT NULL, avg_price DOUBLE PRECISION NOT NULL, current_price DOUBLE PRECISION NOT NULL
    );
    CREATE TABLE IF NOT EXISTS waitlist(
      id SERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    c.commit()

@app.before_request
def setup():
    init_db()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("uid"):
            return jsonify(error="login_required"), 401
        return fn(*args, **kwargs)
    return wrapper

@app.get("/health")
def health():
    return jsonify(status="ok")

@app.get("/")
def landing():
    return render_template("landing.html", logged=bool(session.get("uid")))

@app.get("/app")
def app_page():
    return render_template("index.html", logged=bool(session.get("uid")))

@app.post("/api/waitlist")
def waitlist():
    data=request.get_json() or {}
    email=str(data.get("email","")).strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify(error="Introduce un email válido."),400
    c=db()
    try:
        c.execute("INSERT INTO waitlist(email) VALUES(?)",(email,))
        c.commit()
    except psycopg.errors.UniqueViolation:
        c.rollback()
        pass
    return jsonify(ok=True,message="Te hemos apuntado a la beta.")


@app.post("/api/register")
def register():
    data=request.get_json() or {}
    email=str(data.get("email","")).strip().lower()
    pw=str(data.get("password",""))
    if "@" not in email or len(pw)<8:
        return jsonify(error="Email válido y contraseña de 8 caracteres mínimo."),400
    try:
        cur=db().execute("INSERT INTO users(email,password_hash) VALUES(?,?) RETURNING id",
                         (email,generate_password_hash(pw)))
        uid=cur.fetchone()["id"]
        for name,kind in [("Cuenta principal","Banco"),("Revolut","Banco"),("Trade Republic","Ahorro / inversión"),("Efectivo","Efectivo")]:
            db().execute("INSERT INTO accounts(user_id,name,kind,balance) VALUES(?,?,?,0)",(uid,name,kind))
        db().commit()
        session["uid"]=uid
        return jsonify(ok=True)
    except psycopg.errors.UniqueViolation:
        c.rollback()
        return jsonify(error="Ese email ya está registrado."),409

@app.post("/api/login")
def login():
    data=request.get_json() or {}
    row=db().execute("SELECT * FROM users WHERE email=?",(str(data.get("email","")).strip().lower(),)).fetchone()
    if not row or not check_password_hash(row["password_hash"],str(data.get("password",""))):
        return jsonify(error="Credenciales incorrectas."),401
    session["uid"]=row["id"]
    return jsonify(ok=True)

@app.post("/api/logout")
def logout():
    session.clear(); return jsonify(ok=True)

@app.get("/api/me")
@login_required
def me():
    u=db().execute("SELECT id,email FROM users WHERE id=?",(session["uid"],)).fetchone()
    return jsonify(dict(u))

def rows(sql,args=()):
    return [dict(x) for x in db().execute(sql,args).fetchall()]

@app.get("/api/dashboard")
@login_required
def dashboard():
    uid=session["uid"]; month=date.today().strftime("%Y-%m")
    accounts=rows("SELECT * FROM accounts WHERE user_id=? ORDER BY id",(uid,))
    tx=rows("SELECT * FROM transactions WHERE user_id=? ORDER BY tx_date DESC,id DESC LIMIT 100",(uid,))
    mt=[x for x in tx if x["tx_date"].startswith(month)]
    inc=sum(x["amount"] for x in mt if x["kind"]=="income"); exp=sum(x["amount"] for x in mt if x["kind"]=="expense")
    inv=rows("SELECT * FROM investments WHERE user_id=?",(uid,))
    inv_value=sum(x["units"]*x["current_price"] for x in inv)
    return jsonify(accounts=accounts,transactions=tx,income=inc,expense=exp,saving=inc-exp,
                   investments=inv,portfolio_value=inv_value,
                   net_worth=sum(x["balance"] for x in accounts)+inv_value)

@app.post("/api/accounts")
@login_required
def add_account():
    d=request.get_json() or {}
    name=str(d.get("name","")).strip()
    if not name:return jsonify(error="Nombre requerido"),400
    cur=db().execute("INSERT INTO accounts(user_id,name,kind,balance) VALUES(?,?,?,?) RETURNING id",
                     (session["uid"],name,d.get("kind","Banco"),float(d.get("balance",0))))
    aid=cur.fetchone()["id"]
    db().commit(); return jsonify(id=aid)

@app.patch("/api/accounts/<int:aid>")
@login_required
def patch_account(aid):
    d=request.get_json() or {}
    cur=db().execute("UPDATE accounts SET balance=? WHERE id=? AND user_id=?",(float(d.get("balance",0)),aid,session["uid"]))
    db().commit(); return jsonify(ok=cur.rowcount==1)

@app.post("/api/transactions")
@login_required
def add_tx():
    d=request.get_json() or {}; uid=session["uid"]
    amount=float(d.get("amount",0))
    if amount<=0:return jsonify(error="Importe inválido"),400
    acc=db().execute("SELECT * FROM accounts WHERE id=? AND user_id=?",(int(d["account_id"]),uid)).fetchone()
    if not acc:return jsonify(error="Cuenta no válida"),400
    kind=d.get("kind","expense")
    db().execute("""INSERT INTO transactions(user_id,account_id,kind,amount,category,description,tx_date)
                    VALUES(?,?,?,?,?,?,?)""",(uid,acc["id"],kind,amount,d.get("category","Otros"),d.get("description",""),d.get("tx_date",str(date.today()))))
    delta=amount if kind=="income" else -amount
    db().execute("UPDATE accounts SET balance=balance+? WHERE id=?",(delta,acc["id"]))
    db().commit(); return jsonify(ok=True)

@app.post("/api/budgets")
@login_required
def budget():
    d=request.get_json() or {}; uid=session["uid"]
    db().execute("INSERT INTO budgets(user_id,category,monthly_limit) VALUES(?,?,?)",(uid,d["category"],float(d["monthly_limit"])))
    db().commit(); return jsonify(ok=True)

@app.get("/api/budgets")
@login_required
def get_budgets():
    uid=session["uid"]; month=date.today().strftime("%Y-%m")
    b=rows("SELECT * FROM budgets WHERE user_id=? ORDER BY category",(uid,))
    spent=rows("""SELECT category,SUM(amount) spent FROM transactions
                  WHERE user_id=? AND kind='expense' AND substr(tx_date,1,7)=?
                  GROUP BY category""",(uid,month))
    sm={x["category"]:x["spent"] for x in spent}
    for x in b:x["spent"]=sm.get(x["category"],0)
    return jsonify(budgets=b)

@app.post("/api/goals")
@login_required
def goal():
    d=request.get_json() or {}
    db().execute("INSERT INTO goals(user_id,name,target,current,target_date) VALUES(?,?,?,?,?)",
                 (session["uid"],d["name"],float(d["target"]),float(d.get("current",0)),d.get("target_date")))
    db().commit(); return jsonify(ok=True)

@app.get("/api/goals")
@login_required
def goals(): return jsonify(goals=rows("SELECT * FROM goals WHERE user_id=? ORDER BY target_date",(session["uid"],)))

@app.post("/api/investments")
@login_required
def investment():
    d=request.get_json() or {}
    db().execute("INSERT INTO investments(user_id,name,units,avg_price,current_price) VALUES(?,?,?,?,?)",
                 (session["uid"],d["name"],float(d["units"]),float(d["avg_price"]),float(d["current_price"])))
    db().commit(); return jsonify(ok=True)

@app.patch("/api/investments/<int:iid>")
@login_required
def update_investment(iid):
    d=request.get_json() or {}
    cur=db().execute("UPDATE investments SET current_price=? WHERE id=? AND user_id=?",
                     (float(d["current_price"]),iid,session["uid"]))
    db().commit(); return jsonify(ok=cur.rowcount==1)

@app.post("/api/recurring")
@login_required
def recurring():
    d=request.get_json() or {}
    db().execute("""INSERT INTO recurring(user_id,kind,name,amount,category,day_of_month)
                    VALUES(?,?,?,?,?,?)""",(session["uid"],d["kind"],d["name"],float(d["amount"]),d["category"],int(d.get("day_of_month",1))))
    db().commit(); return jsonify(ok=True)

@app.get("/api/recurring")
@login_required
def get_recurring(): return jsonify(recurring=rows("SELECT * FROM recurring WHERE user_id=? ORDER BY day_of_month",(session["uid"],)))

@app.post("/api/import-csv")
@login_required
def import_csv():
    f=request.files.get("file")
    if not f:return jsonify(error="Falta el CSV"),400
    # Expected columns: date,kind,amount,category,description,account
    text=f.stream.read().decode("utf-8-sig")
    reader=csv.DictReader(io.StringIO(text))
    uid=session["uid"]; added=0
    for r in reader:
        try:
            acc=db().execute("SELECT id FROM accounts WHERE user_id=? AND name=?",(uid,r["account"].strip())).fetchone()
            if not acc: continue
            amount=float(r["amount"].replace(",","."))
            kind=r["kind"].strip().lower()
            if kind not in ("income","expense") or amount<=0: continue
            db().execute("""INSERT INTO transactions(user_id,account_id,kind,amount,category,description,tx_date)
                            VALUES(?,?,?,?,?,?,?)""",(uid,acc["id"],kind,amount,r.get("category","Otros"),r.get("description",""),r["date"]))
            delta=amount if kind=="income" else -amount
            db().execute("UPDATE accounts SET balance=balance+? WHERE id=?",(delta,acc["id"]))
            added+=1
        except Exception: pass
    db().commit(); return jsonify(added=added)


if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
